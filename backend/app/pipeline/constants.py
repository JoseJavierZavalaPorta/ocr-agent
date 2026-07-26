# =============================================================================
# constants.py — Constantes configurables del pipeline OCR
#
# Editar este archivo para ajustar prompts, umbrales y parámetros del pipeline
# sin tener que buscar en todo el código.
# =============================================================================

# -----------------------------------------------------------------------------
# PROMPTS LLM (corrector.py)
# -----------------------------------------------------------------------------

PROMPT_CORRECTION_PRINTED = """Eres un corrector de texto extraído por OCR de documentos escaneados en español. Tu única tarea es limpiar errores de OCR SIN alterar el significado ni inventar nada.

El texto puede contener: errores de caracteres (1/l/I, 0/O, rn/m, cl/d, acentos faltantes), artefactos del scanner (símbolos "|" sueltos, números aislados de ruido), palabras partidas y espaciado o saltos de línea incorrectos.

REGLAS OBLIGATORIAS:
1. Corrige errores de caracteres y espaciado usando el contexto de la frase.
2. Elimina artefactos obvios del scanner (símbolos sueltos, ruido numérico sin sentido).
3. NO inventes, completes ni agregues información que no esté en el texto. Si una parte no se entiende, déjala lo más fiel posible al original — nunca la reemplaces por contenido plausible.
4. Preserva EXACTAMENTE números, fechas, cifras monetarias, porcentajes, nombres propios y códigos.
5. NUNCA te niegues a procesar el texto. NUNCA agregues comentarios, explicaciones, ni frases como "el texto no corresponde a...". Aunque el contenido no sea el que esperas, límpialo igual.
6. NO agregues títulos, etiquetas ni estructura que no estén en el original.
7. Responde ÚNICAMENTE con el texto corregido.

TEXTO OCR:
{ocr_text}

TEXTO CORREGIDO:"""

PROMPT_CORRECTION_HANDWRITING = """Eres un corrector de texto extraído por OCR de documentos históricos en español (con frecuencia actas y documentos administrativos o económicos, por ejemplo del Banco Central de Reserva del Perú, aunque pueden ser de cualquier tema). Tu única tarea es limpiar errores de OCR SIN inventar contenido.

El OCR de escritura a mano o mecanografía antigua produce errores típicos: letras confundidas (a/u/o, n/u, r/n, l/i, b/h), sílabas transpuestas, palabras cortadas.

REGLAS OBLIGATORIAS:
1. Corrige errores de caracteres usando el contexto de la frase.
2. NO inventes, completes ni agregues información que no esté en el texto. Si una palabra o frase no se entiende, déjala lo más fiel posible al original — nunca la reemplaces por contenido plausible (ej: no agregues cifras, tasas, acuerdos ni nombres que no estén escritos).
3. Preserva EXACTAMENTE números, fechas, cifras monetarias, porcentajes, nombres propios y códigos. No cambies el nombre de la moneda que aparezca (Libra peruana, Sol, Sol de Oro, Inti, Nuevo Sol).
4. NUNCA te niegues a procesar el texto. NUNCA agregues comentarios, explicaciones, ni frases como "el texto no corresponde a un acta del BCRP...". Aunque el contenido no sea el que esperas, límpialo igual.
5. NO agregues títulos, etiquetas ni estructura que no estén en el original.
6. Responde ÚNICAMENTE con el texto corregido.

TEXTO OCR:
{ocr_text}

TEXTO CORREGIDO:"""

# Prompt de resumen ejecutivo + clasificación (summarizer.py).
# {categorias_texto}: lista "- nombre: descripcion" formateada por summarizer.py.
# {md_text}: el .md completo del documento ya corregido.
# Se combina con el parámetro format=json de Ollama, que fuerza JSON válido
# a nivel de servidor — igual se pide explícitamente el esquema en el prompt
# para que el modelo sepa qué claves usar.
PROMPT_SUMMARY_CLASSIFICATION = """Eres un analista documental. Vas a leer un documento en español (ya transcrito de OCR) y debes:
1. Escribir un resumen ejecutivo claro y conciso (5-10 líneas) en español, con los datos y hechos más relevantes del documento.
2. Clasificarlo eligiendo ÚNICAMENTE entre las categorías de la siguiente lista — no inventes categorías nuevas. Ordena hasta 5 categorías de mayor a menor relevancia, con un score de 0.0 a 1.0 y una justificación breve (1 línea) por cada una. Si el documento claramente pertenece a menos de 5 categorías, incluye solo las que apliquen.

CATEGORÍAS DISPONIBLES:
{categorias_texto}

DOCUMENTO:
{md_text}

Responde ÚNICAMENTE con un JSON con esta forma exacta, sin texto adicional antes ni después:
{{
  "resumen_ejecutivo": "...",
  "clasificacion_top5": [
    {{"categoria": "nombre exacto de la lista", "score": 0.0, "justificacion": "..."}}
  ]
}}"""

# Máximo de caracteres del .md que se envía al LLM para resumen/clasificación
# (documento completo, no por página — límite más alto que la corrección).
SUMMARY_MAX_INPUT_CHARS = 12000

# Parámetros de generación del LLM de resumen/clasificación (qwen2.5:32b vía Ollama)
SUMMARY_TEMPERATURE = 0.1
SUMMARY_MAX_TOKENS = 1024
SUMMARY_CONTEXT_LENGTH = 8192

# Plantilla del archivo {stem}_resumen.md (summary_tasks.py).
# {filename}: nombre del documento original. {resumen}: resumen ejecutivo del LLM.
# {items}: lista ya formateada de las top-5 categorías (una línea por categoría,
# usando RESUMEN_MD_ITEM_TEMPLATE de abajo).
RESUMEN_MD_TEMPLATE = """# Resumen ejecutivo — {filename}

{resumen}

## Clasificación (top 5)

{items}
"""

# Una línea del listado de categorías dentro de RESUMEN_MD_TEMPLATE.
# {rank}: 1-5. {categoria}: nombre exacto de categorias.json. {score}: 0.0-1.0.
# {justificacion}: explicación breve que da el LLM.
RESUMEN_MD_ITEM_TEMPLATE = "{rank}. **{categoria}** (score: {score:.2f}) — {justificacion}"

# Prompt que envía VisionEngine (minicpm-v) junto con la imagen
PROMPT_VISION_OCR = (
    "Transcribe fielmente TODO el texto visible en esta imagen, exactamente como aparece. "
    "Es un documento en español (puede ser un acta, oficio, ley, tabla, carta u otro documento "
    "administrativo o económico).\n"
    "REGLAS ESTRICTAS:\n"
    "- Transcribe ÚNICAMENTE lo que está escrito en la imagen. NO inventes, completes, infieras "
    "ni agregues nada que no esté visiblemente presente (no agregues cifras, tasas, fechas, "
    "nombres ni acuerdos que no se vean).\n"
    "- NO agregues títulos, etiquetas ni secciones que no aparezcan en el documento "
    "(no uses '**Título:**', '**Body Text:**', '**Encabezado:**' ni similares).\n"
    "- NO describas la imagen ni agregues comentarios tuyos.\n"
    "- Preserva números, fechas, cifras y nombres tal como se ven.\n"
    "- Para texto manuscrito cursivo, transcríbelo lo mejor posible según lo que realmente veas.\n"
    "- Si una parte no es legible, omítela; NO la reemplaces con texto inventado.\n"
    "- Responde ÚNICAMENTE con el texto transcrito, sin explicaciones."
)

# -----------------------------------------------------------------------------
# PARÁMETROS DEL PIPELINE (pipeline.py)
# -----------------------------------------------------------------------------

# Umbral de palabras para decidir si VisionEngine supera a MinerU en páginas MIXED/HW.
# Si MinerU extrajo MENOS de este número de palabras → se prueba VisionEngine.
# Referencia: receta médica ~30 palabras, página de texto completa 200+ palabras.
VISION_WORD_THRESHOLD = 80

# Mínimo de caracteres para considerar que un resultado OCR es válido (no vacío/ruido).
VISION_MIN_CHARS = 20

# Ratio de handwriting_score para activar TrOCR como fallback cuando MinerU falla.
# Se multiplica por settings.handwriting_threshold (ej: 0.85 * 0.7 = 0.595).
HANDWRITING_FALLBACK_RATIO = 0.7

# Mínimo de caracteres reales para considerar que MinerU extrajo texto (no solo imágenes).
MINERU_MIN_REAL_CHARS = 30

# -----------------------------------------------------------------------------
# PARÁMETROS LLM CORRECTOR (corrector.py)
# -----------------------------------------------------------------------------

# Máximo de caracteres del texto OCR que se envía al LLM para corrección.
LLM_MAX_INPUT_CHARS = 4000

# Parámetros de generación del LLM de corrección (qwen2.5:32b vía Ollama)
LLM_TEMPERATURE = 0.1
LLM_TOP_P = 0.9
LLM_MAX_TOKENS = 512
LLM_CONTEXT_LENGTH = 4096

# -----------------------------------------------------------------------------
# PARÁMETROS VISION ENGINE (ocr_engine.py)
# -----------------------------------------------------------------------------

# Calidad JPEG al enviar imagen a VisionEngine (0-100)
VISION_JPEG_QUALITY = 92

# Parámetros de generación del modelo Vision (minicpm-v vía Ollama)
VISION_TEMPERATURE = 0.1
VISION_MAX_TOKENS = 1024

# Timeout en segundos para la llamada HTTP al VisionEngine
# CPU puro (VisionEngine/minicpm-v vía Ollama) puede tardar varios minutos
# por página en hardware modesto — 180s se quedaba corto en pruebas reales.
VISION_TIMEOUT_SEC = 300

# Confianza asignada al resultado de VisionEngine según longitud del texto extraído
VISION_CONFIDENCE_OK = 0.82    # cuando extrae texto suficiente (> VISION_MIN_CHARS)
VISION_CONFIDENCE_LOW = 0.30   # cuando el texto extraído es muy corto

# -----------------------------------------------------------------------------
# PARÁMETROS MINERU ENGINE (ocr_engine.py)
# -----------------------------------------------------------------------------

# Timeout en segundos para la ejecución de magic-pdf CLI. 300s ya tocó el
# límite en pruebas reales bajo carga concurrente (worker + Ollama a la vez).
MINERU_TIMEOUT_SEC = 420

# Confianza asignada a resultados de MinerU
MINERU_CONFIDENCE_OK = 0.85
MINERU_CONFIDENCE_EMPTY = 0.10
