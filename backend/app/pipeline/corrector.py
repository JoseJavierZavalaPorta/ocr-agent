import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import get_settings
from app.pipeline.constants import (
    PROMPT_CORRECTION_PRINTED,
    PROMPT_CORRECTION_HANDWRITING,
    LLM_MAX_INPUT_CHARS,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_MAX_TOKENS,
    LLM_CONTEXT_LENGTH,
)

settings = get_settings()


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

        template = PROMPT_CORRECTION_HANDWRITING if is_handwriting else PROMPT_CORRECTION_PRINTED
        prompt = template.format(ocr_text=ocr_text[:LLM_MAX_INPUT_CHARS])
        model = self._model

        try:
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": LLM_TEMPERATURE,
                        "top_p": LLM_TOP_P,
                        "num_predict": LLM_MAX_TOKENS,
                        "num_ctx": LLM_CONTEXT_LENGTH,
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
