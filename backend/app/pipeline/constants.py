# =============================================================================
# constants.py — Constantes configurables del pipeline OCR
#
# Editar este archivo para ajustar prompts, umbrales y parámetros del pipeline
# sin tener que buscar en todo el código.
# =============================================================================

# -----------------------------------------------------------------------------
# PROMPTS LLM (corrector.py)
# -----------------------------------------------------------------------------

PROMPT_CORRECTION_PRINTED = """Eres un experto en limpieza y normalización de texto extraído por OCR de documentos escaneados en español.

El texto puede contener:
- Errores de caracteres: 1/l/I, 0/O, rn/m, cl/d, acentos faltantes
- Artefactos de layout: números aislados sin contexto, fragmentos de borde de tabla ("|", "—"), coordenadas numéricas sueltas
- Fragmentos cortados al inicio de línea por el borde del scanner
- Palabras partidas, espaciado incorrecto, saltos de línea incorrectos

INSTRUCCIONES:
1. Elimina artefactos OCR obvios: números aislados sin contexto semántico, símbolos "|" sueltos, cadenas numéricas que claramente son ruido del scanner.
2. Corrige errores de caracteres usando el contexto de la frase.
3. Normaliza espaciado y saltos de línea para que el texto sea legible.
4. Preserva TODOS los datos reales: nombres propios, fechas, números de documento/acta, códigos, cifras monetarias, términos económicos/institucionales.
5. Si un fragmento está cortado por el borde del scan, indícalo con [...].
6. Preserva el formato Markdown existente (encabezados, listas).
7. Responde ÚNICAMENTE con el texto limpio y normalizado, sin explicaciones.

TEXTO OCR:
{ocr_text}

TEXTO NORMALIZADO:"""

PROMPT_CORRECTION_HANDWRITING = """Eres un experto en transcripción de actas históricas del Banco Central de Reserva del Perú (BCRP) — actas de Directorio y documentos económicos/financieros, manuscritos o mecanografiados.

Tienes conocimiento de:
- Estructura típica de un acta de Directorio del BCRP: fecha y número de sesión/acta, directores y funcionarios presentes (Presidente del Directorio, Gerente General, Directores, Secretario), orden del día, acuerdos adoptados, firmas.
- Terminología económica y bancaria de la época: tasa de redescuento, tasa de interés, encaje bancario/legal, emisión monetaria, reservas internacionales, tipo de cambio, operaciones de mercado abierto, política monetaria, circulante, cartera de créditos, balance general.
- Nombres históricos de la moneda peruana según la época del documento — preserva el nombre EXACTO que aparece, no lo "corrijas" a otro: Sol / Libra peruana (hasta ~1930), Sol de Oro (~1930-1985), Inti (1985-1991), Nuevo Sol (1991-2015), Sol (desde 2015).
- Cifras monetarias, porcentajes, fechas y números de acta/sesión son datos críticos: preservarlos exactamente, sin redondear ni "corregir" su valor.

El OCR de escritura a mano o mecanografía antigua produce errores típicos: letras confundidas (a/u/o, n/u, r/n, l/i, b/h), sílabas transpuestas, palabras cortadas.

INSTRUCCIONES:
1. Usa el contexto económico/institucional para inferir palabras garbled (ej: términos bancarios, nombres de directores, denominación de la moneda vigente en esa época).
2. Corrige errores de caracteres usando coherencia semántica y conocimiento del dominio económico/bancario — NO asumas contenido médico, legal genérico u otro dominio ajeno a actas de banco central.
3. Para nombres propios de directores o funcionarios ilegibles, conserva la mejor aproximación posible.
4. Para fragmentos completamente indescifrables, escribe [ilegible].
5. Preserva TODOS los números exactamente: cifras monetarias, tasas, porcentajes, fechas, números de acta/sesión.
6. NO inventes datos que no estén presentes en el texto.
7. Responde ÚNICAMENTE con el texto transcrito y corregido, sin explicaciones ni comentarios.

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
    "Transcribe todo el texto visible en esta imagen exactamente como aparece. "
    "Es un acta histórica del Banco Central de Reserva del Perú (BCRP) — un acta de Directorio "
    "u otro documento económico/financiero, manuscrito o mecanografiado. "
    "Preserva la estructura: encabezados, fecha, número de acta/sesión, nombres de directores "
    "o funcionarios, cifras monetarias, acuerdos adoptados. "
    "Para texto manuscrito cursivo, transcríbelo lo mejor posible usando el contexto. "
    "Para fragmentos completamente ilegibles escribe [ilegible]. "
    "Responde ÚNICAMENTE con el texto transcrito, sin explicaciones."
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
