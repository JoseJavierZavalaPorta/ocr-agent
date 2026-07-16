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
4. Preserva TODOS los datos reales: nombres propios, fechas, números de documento, DNI, códigos, términos legales/médicos/técnicos.
5. Si un fragmento está cortado por el borde del scan, indícalo con [...].
6. Preserva el formato Markdown existente (encabezados, listas).
7. Responde ÚNICAMENTE con el texto limpio y normalizado, sin explicaciones.

TEXTO OCR:
{ocr_text}

TEXTO NORMALIZADO:"""

PROMPT_CORRECTION_HANDWRITING = """Eres un experto en transcripción de documentos manuscritos en español: recetas médicas, cartas, formularios y actas.

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

# Prompt que envía VisionEngine (minicpm-v) junto con la imagen
PROMPT_VISION_OCR = (
    "Transcribe todo el texto visible en esta imagen exactamente como aparece. "
    "Es un documento en español (puede ser una receta médica, carta, formulario, acta, "
    "censo, padrón, contrato u otro documento histórico o moderno). "
    "Preserva la estructura: encabezados, campos, líneas. "
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
VISION_TIMEOUT_SEC = 180

# Confianza asignada al resultado de VisionEngine según longitud del texto extraído
VISION_CONFIDENCE_OK = 0.82    # cuando extrae texto suficiente (> VISION_MIN_CHARS)
VISION_CONFIDENCE_LOW = 0.30   # cuando el texto extraído es muy corto

# -----------------------------------------------------------------------------
# PARÁMETROS MINERU ENGINE (ocr_engine.py)
# -----------------------------------------------------------------------------

# Timeout en segundos para la ejecución de magic-pdf CLI
MINERU_TIMEOUT_SEC = 300

# Confianza asignada a resultados de MinerU
MINERU_CONFIDENCE_OK = 0.85
MINERU_CONFIDENCE_EMPTY = 0.10
