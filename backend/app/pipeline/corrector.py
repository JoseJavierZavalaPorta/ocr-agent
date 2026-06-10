import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import get_settings

settings = get_settings()

_CORRECTION_PROMPT = """Eres un experto en corrección de documentos históricos en español (1900-actualidad).
Se te proporciona texto extraído por OCR de un documento escaneado. El texto puede contener errores típicos de OCR:
caracteres confundidos (1/l/I, 0/O, rn/m, cl/d, etc.), palabras partidas, espacios incorrectos, acentos faltantes.

REGLAS:
1. Corrige SOLO errores evidentes de OCR. NO reescribas ni parafrasees.
2. Preserva nombres propios, lugares, fechas y términos legales/técnicos exactamente.
3. Preserva la puntuación original incluso si parece anticuada.
4. Si una palabra es ambigua, elige la opción más coherente con el contexto histórico.
5. Preserva el formato Markdown (si hay tablas, listas, encabezados).
6. Responde ÚNICAMENTE con el texto corregido, sin explicaciones ni comentarios.

TEXTO OCR:
{ocr_text}

TEXTO CORREGIDO:"""

_CORRECTION_PROMPT_HANDWRITING = """Eres un experto en transcripción de manuscritos históricos en español.
Se te proporciona texto extraído por OCR de un manuscrito escaneado. El texto puede ser impreciso.

REGLAS:
1. Corrige errores obvios preservando el estilo de escritura original.
2. Si el texto es ilegible en un fragmento, escribe [ilegible].
3. Preserva abreviaturas históricas (q. = que, etc.).
4. NO inventes ni completes información faltante.
5. Responde ÚNICAMENTE con el texto corregido.

TEXTO OCR:
{ocr_text}

TEXTO CORREGIDO:"""


class LLMCorrector:
    """Corrector contextual vía Ollama (llama3.1:8b). Funciona 100% offline."""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(120.0),
        )
        self._model = settings.ollama_correction_model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def correct(self, ocr_text: str, is_handwriting: bool = False) -> tuple[str, float]:
        """
        Retorna (texto_corregido, ratio_cambio).
        ratio_cambio: 0.0 = sin cambios, 1.0 = completamente reescrito.
        """
        if not ocr_text or not ocr_text.strip():
            return ocr_text, 0.0

        template = _CORRECTION_PROMPT_HANDWRITING if is_handwriting else _CORRECTION_PROMPT
        prompt = template.format(ocr_text=ocr_text[:4000])  # límite de contexto

        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "num_predict": 2048,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            corrected = data.get("response", ocr_text).strip()

            ratio = self._compute_change_ratio(ocr_text, corrected)
            logger.debug(f"Corrección LLM: ratio_cambio={ratio:.2f}")
            return corrected, ratio

        except Exception as e:
            logger.error(f"Error en corrección LLM: {e}. Usando texto OCR original.")
            return ocr_text, 0.0

    def _compute_change_ratio(self, original: str, corrected: str) -> float:
        """Distancia de edición normalizada entre original y corregido."""
        if not original:
            return 0.0
        orig_words = set(original.lower().split())
        corr_words = set(corrected.lower().split())
        if not orig_words:
            return 0.0
        intersection = len(orig_words & corr_words)
        union = len(orig_words | corr_words)
        jaccard_sim = intersection / (union + 1e-8)
        return 1.0 - jaccard_sim

    async def close(self):
        await self._client.aclose()
