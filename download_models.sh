#!/usr/bin/env bash
# =============================================================================
# download_models.sh
# Descarga TODOS los modelos necesarios. Ejecutar UNA VEZ con internet.
# Después de esto el sistema opera completamente offline.
# Ejecutar DENTRO del container worker:
#   docker compose exec worker bash /app/download_models.sh
# =============================================================================

set -euo pipefail

MODELS_PATH="${MODELS_PATH:-/data/models}"
HF_CACHE="${MODELS_PATH}/huggingface"
MARKER_CACHE="${MODELS_PATH}/marker"
OLLAMA_URL="${OLLAMA_URL:-http://ollama:11434}"
OLLAMA_MODEL="${OLLAMA_CORRECTION_MODEL:-llama3.1:8b}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error_()  { echo -e "${RED}[ERROR]${NC} $*"; }
step()    { echo -e "\n${GREEN}▶ $*${NC}"; }

# ── 1. Surya / Marker models ─────────────────────────────────────────────────
step "Descargando modelos Surya OCR (via marker-pdf)..."
export HF_HOME="$HF_CACHE"
export TRANSFORMERS_CACHE="$HF_CACHE"
export MARKER_MODELS_DIR="$MARKER_CACHE"

python3 - <<'PYEOF'
import os
os.environ.setdefault("HF_HOME", os.environ.get("HF_HOME", "/data/models/huggingface"))
os.environ.setdefault("TRANSFORMERS_CACHE", os.environ.get("HF_HOME", "/data/models/huggingface"))

print("  Cargando modelos Surya (detección + reconocimiento + layout)...")
try:
    from surya.model.detection.segformer import load_model as load_det, load_processor as load_det_proc
except ImportError:
    try:
        from surya.model.detection.model import load_model as load_det, load_processor as load_det_proc
    except ImportError:
        from surya.model.detection import load_model as load_det, load_processor as load_det_proc

from surya.model.recognition.model import load_model as load_rec
from surya.model.recognition.processor import load_processor as load_rec_proc

# surya 0.6.x: SuryaOCRConfig bug — silenciar INFO de transformers para evitar KeyError
import transformers as _hf
_hf.logging.set_verbosity_error()
det_proc = load_det_proc()
det_model = load_det()
rec_model = load_rec()
rec_proc = load_rec_proc()
_hf.logging.set_verbosity_warning()
print("  ✓ Surya OCR descargado")

try:
    from surya.model.layout.model import load_model as load_layout
    from surya.model.layout.processor import load_processor as load_layout_proc
    load_layout_proc()
    load_layout()
    print("  ✓ Surya Layout descargado")
except Exception as e:
    print(f"  ⚠ Surya Layout no disponible: {e}")
PYEOF

# ── 2. TrOCR (manuscritos) ───────────────────────────────────────────────────
step "Descargando TrOCR (manuscritos: microsoft/trocr-large-handwritten)..."
python3 - <<'PYEOF'
import os
cache = os.environ.get("HF_HOME", "/data/models/huggingface")
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
print("  Descargando processor TrOCR...")
TrOCRProcessor.from_pretrained("microsoft/trocr-large-handwritten", cache_dir=cache)
print("  Descargando modelo TrOCR (~1.8GB)...")
VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-large-handwritten", cache_dir=cache)
print("  ✓ TrOCR descargado")
PYEOF

# ── 3. MinerU models (descarga automática en primer uso) ─────────────────────
step "Pre-calentando MinerU (magic-pdf)..."
python3 - <<'PYEOF'
import os
cache = os.environ.get("MODELS_PATH", "/data/models")
os.environ.setdefault("MINERU_MODELS_DIR", f"{cache}/mineru")
try:
    import subprocess
    # MinerU descarga sus modelos en el primer run
    result = subprocess.run(
        ["magic-pdf", "--help"],
        capture_output=True, timeout=30
    )
    if result.returncode == 0:
        print("  ✓ MinerU disponible")
        # Trigger descarga de modelos MinerU
        import magic_pdf.model.doc_analyze_by_custom_model as _  # noqa
        print("  ✓ MinerU modelos cargados")
    else:
        print("  ⚠ MinerU no disponible (se usará Surya como fallback)")
except Exception as e:
    print(f"  ⚠ MinerU skip: {e}")
PYEOF

# ── 4. Ollama model ───────────────────────────────────────────────────────────
step "Descargando modelo Ollama: $OLLAMA_MODEL..."
MAX_RETRIES=10
RETRY_DELAY=5

for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
        break
    fi
    warn "Ollama no disponible aún, esperando... ($i/$MAX_RETRIES)"
    sleep $RETRY_DELAY
done

if ! curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    error_ "Ollama no responde. Verificar que el container ollama esté corriendo."
    exit 1
fi

info "Descargando $OLLAMA_MODEL (puede tardar varios minutos)..."
curl -s -X POST "${OLLAMA_URL}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$OLLAMA_MODEL\", \"stream\": false}" \
    | python3 -c "import sys, json; d=json.load(sys.stdin); print('  ✓ Ollama:', d.get('status', 'ok'))"

# ── 5. Tesseract datos español ────────────────────────────────────────────────
step "Verificando Tesseract español..."
if tesseract --list-langs 2>/dev/null | grep -q "spa"; then
    info "✓ Tesseract español disponible"
else
    warn "Tesseract español no detectado. Instalando..."
    apt-get install -y tesseract-ocr-spa 2>/dev/null || true
fi

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ Descarga de modelos completada${NC}"
echo -e "${GREEN}  El sistema puede operar 100% offline ahora.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
du -sh "${MODELS_PATH}"/* 2>/dev/null | sort -h || true
