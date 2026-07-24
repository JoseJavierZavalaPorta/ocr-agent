import json
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_settings
from app.pipeline.constants import (
    PROMPT_SUMMARY_CLASSIFICATION,
    SUMMARY_MAX_INPUT_CHARS,
    SUMMARY_TEMPERATURE,
    SUMMARY_MAX_TOKENS,
    SUMMARY_CONTEXT_LENGTH,
)

settings = get_settings()


class SummarizerError(Exception):
    """La llamada a Ollama falló, o la respuesta no se pudo interpretar como el JSON esperado."""


class DocumentSummarizer:
    """Resumen ejecutivo + clasificación top-5 vía Ollama. Reutiliza el mismo
    modelo que ya usa el corrector de OCR (settings.ollama_correction_model) —
    ya está cargado en Ollama, no agrega costo de RAM extra."""

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(300.0),
        )
        self._model = settings.ollama_correction_model

    @staticmethod
    def _format_categorias(categorias: list[dict]) -> str:
        return "\n".join(f"- {c['nombre']}: {c['descripcion']}" for c in categorias)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def summarize_and_classify(self, md_text: str, categorias: list[dict]) -> dict:
        """
        Retorna {"resumen_ejecutivo": str, "clasificacion_top5": [{"categoria", "score", "justificacion"}, ...]}.
        Levanta SummarizerError si Ollama falla o la respuesta no es interpretable
        tras reintentar — quien llame debe capturarla, no debe tumbar el worker.
        """
        categorias_texto = self._format_categorias(categorias)
        nombres_validos = {c["nombre"] for c in categorias}
        prompt = PROMPT_SUMMARY_CLASSIFICATION.format(
            categorias_texto=categorias_texto,
            md_text=md_text[:SUMMARY_MAX_INPUT_CHARS],
        )

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await self._client.post(
                    "/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {
                            "temperature": SUMMARY_TEMPERATURE,
                            "num_predict": SUMMARY_MAX_TOKENS,
                            "num_ctx": SUMMARY_CONTEXT_LENGTH,
                        },
                    },
                )
                response.raise_for_status()
                raw = response.json().get("response", "")
                result = self._parse_and_validate(raw, nombres_validos)
                return result
            except (httpx.ConnectError, httpx.TimeoutException):
                raise  # deja que @retry maneje los reintentos de red
            except Exception as e:
                last_error = e
                logger.warning(f"Resumen/clasificación intento {attempt + 1} falló: {e}")

        raise SummarizerError(f"No se pudo obtener resumen/clasificación válida tras reintentos: {last_error}")

    def _parse_and_validate(self, raw: str, nombres_validos: set[str]) -> dict:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise SummarizerError(f"Respuesta de Ollama no es JSON válido: {e}. Raw: {raw[:300]!r}") from e

        if not isinstance(data, dict) or "resumen_ejecutivo" not in data or "clasificacion_top5" not in data:
            raise SummarizerError(f"JSON de Ollama no tiene las claves esperadas. Recibido: {raw[:300]!r}")

        resumen = str(data["resumen_ejecutivo"]).strip()
        top5_raw = data["clasificacion_top5"]
        if not isinstance(top5_raw, list):
            raise SummarizerError(f"'clasificacion_top5' no es una lista. Recibido: {raw[:300]!r}")

        top5 = []
        for item in top5_raw[:5]:
            if not isinstance(item, dict) or "categoria" not in item:
                continue
            categoria = str(item["categoria"]).strip()
            if categoria not in nombres_validos:
                logger.warning(f"El modelo devolvió una categoría fuera de la lista: {categoria!r} — se descarta")
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            top5.append({
                "categoria": categoria,
                "score": max(0.0, min(1.0, score)),
                "justificacion": str(item.get("justificacion", "")).strip(),
            })

        if not resumen:
            raise SummarizerError(f"'resumen_ejecutivo' vacío. Raw: {raw[:300]!r}")
        if not top5:
            raise SummarizerError(f"Ninguna categoría válida en la respuesta. Raw: {raw[:300]!r}")

        return {"resumen_ejecutivo": resumen, "clasificacion_top5": top5}

    async def close(self):
        await self._client.aclose()
