import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import get_settings

settings = get_settings()

_CORRECTION_PROMPT = """Eres un experto en limpieza y normalización de texto extraído por OCR de documentos escaneados en español.

El texto puede contener:
- Errores de caracteres: 1/l/I, 0/O, rn/m, cl/d, acentos faltantes
- Artefactos de layout: números aislados sin contexto, fragmentos de borde de tabla ("|", "—"), coordenadas numéricas sueltas
- Fragmentos cortados al inicio de línea por el borde del scanner
- Palabras partidas, espaciado incorrecto, saltos de línea incorrectos

INSTRUCCIONES:
1. Elimina artefactos OCR obvios: números aislados sin contexto semántico, símbolos "|" sueltos, cadenas numéricas que claramente son ruido del scanner.
2. Corrige errores de caracteres usando el contexto de la frase.
3. Normaliza espaciado y saltos de línea para que el texto sea legible.
4. Preserva TODOS los datos reales: nombres propios, fechas, números de documento, DNI, códigos, términos legales/médicos/técnicos.
5. Si un fragmento está cortado por el borde del scan, indícalo con [...].
6. Preserva el formato Markdown existente (encabezados, listas).
7. Responde ÚNICAMENTE con el texto limpio y normalizado, sin explicaciones.

TEXTO OCR:
{ocr_text}

TEXTO NORMALIZADO:"""

_CORRECTION_PROMPT_HANDWRITING = """Eres un experto en transcripción de documentos manuscritos en español: recetas médicas, cartas, formularios y actas.

Tienes conocimiento de:
- Medicamentos comunes y sus nombres (Rohypnol, Diazepam, Amoxicilina, Ibuprofeno, etc.)
- Abreviaturas médicas: Rp. (receta), mg (miligramos), comp./cáp. (comprimidos/cápsulas), c/12hs, VO, IM, EV, Dr., M.P. (matrícula profesional)
- Formato de receta: paciente, DNI, edad, medicamento, dosis, cantidad, médico, matrícula, fecha

El OCR de escritura a mano produce errores típicos: letras confundidas (a/u/o, n/u, r/n, l/i, b/h), sílabas transpuestas, palabras cortadas.

INSTRUCCIONES:
1. Usa el contexto del tipo de documento para inferir palabras garbled (ej: en una receta, "Robipinol" → "Rohypnol", "Flunizepamon" → posiblemente un medicamento).
2. Corrige errores de caracteres usando coherencia semántica y conocimiento médico/documental.
3. Para nombres propios de pacientes o médicos ilegibles, conserva la mejor aproximación posible.
4. Para fragmentos completamente indescifrables, escribe [ilegible].
5. Preserva TODOS los números exactamente: DNI, dosis, fechas, matrículas, cantidades.
6. NO inventes datos que no estén presentes en el texto.
7. Responde ÚNICAMENTE con el texto transcrito y corregido, sin explicaciones ni comentarios.

TEXTO OCR:
{ocr_text}

TEXTO CORREGIDO:"""


class LLMCorrector:
    """Corrector contextual vía Ollama. Funciona 100% offline."""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(300.0),
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
        prompt = template.format(ocr_text=ocr_text[:4000])
        model = self._model

        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                        "num_predict": 512,
                        "num_ctx": 4096,
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
