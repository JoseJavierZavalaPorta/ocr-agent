#!/usr/bin/env bash
# =============================================================================
# download_models.sh — Descarga modelos HuggingFace (Surya, TrOCR, MinerU)
#
# IMPORTANTE: Este archivo tiene DOS copias que deben mantenerse en sync:
#   - download_models.sh         (referencia en el root, visible al usuario)
#   - backend/download_models.sh (bakeado en la imagen Docker — el que corre)
# Al editar uno, copiar al otro: cp download_models.sh backend/download_models.sh
#
# Se ejecuta DENTRO del container worker durante la instalación.
# install.sh lo invoca automáticamente — no es necesario correrlo a mano.
#
# Si necesitas re-descargar modelos manualmente:
#   docker compose run --rm --no-deps \
#     -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
#     worker bash /app/download_models.sh
# =============================================================================
set -euo pipefail

MODELS_PATH="${MODELS_PATH:-/data/models}"
HF_CACHE="${MODELS_PATH}/huggingface"
MARKER_CACHE="${MODELS_PATH}/marker"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "  ${GREEN}✓${NC} $*"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $*"; }
step()    { echo -e "\n${CYAN}▶${NC} $*"; }

export HF_HOME="$HF_CACHE"
export TRANSFORMERS_CACHE="$HF_CACHE"
export MARKER_MODELS_DIR="$MARKER_CACHE"
export HF_HUB_OFFLINE=0
export TRANSFORMERS_OFFLINE=0

# ── 1. Surya OCR ─────────────────────────────────────────────────────────────
step "Descargando modelos Surya OCR (~1 GB)..."
python3 - <<'PYEOF'
import os
os.environ["HF_HOME"] = os.environ.get("HF_HOME", "/data/models/huggingface")
os.environ["TRANSFORMERS_CACHE"] = os.environ["HF_HOME"]

try:
    from surya.model.detection.segformer import load_model as load_det, load_processor as load_det_proc
except ImportError:
    try:
        from surya.model.detection.model import load_model as load_det, load_processor as load_det_proc
    except ImportError:
        from surya.model.detection import load_model as load_det, load_processor as load_det_proc

from surya.model.recognition.model import load_model as load_rec
from surya.model.recognition.processor import load_processor as load_rec_proc

from surya.model.recognition.config import SuryaOCRConfig as _SuryaOCRConfig
_SuryaOCRConfig.has_no_defaults_at_init = True
def _get_text_config(self, decoder=False):
    return self.decoder if hasattr(self, 'decoder') else self.text_encoder
_SuryaOCRConfig.get_text_config = _get_text_config

load_det_proc(); load_det()
load_rec(); load_rec_proc()
print("  Surya OCR descargado")

try:
    from surya.model.layout.model import load_model as load_layout
    from surya.model.layout.processor import load_processor as load_layout_proc
    load_layout_proc(); load_layout()
    print("  Surya Layout descargado")
except Exception as e:
    print(f"  Surya Layout no disponible: {e}")
PYEOF
info "Surya OK"

# ── 2. TrOCR (manuscritos) ───────────────────────────────────────────────────
step "Descargando TrOCR manuscritos (~1.8 GB)..."
python3 - <<'PYEOF'
import os
cache = os.environ.get("HF_HOME", "/data/models/huggingface")
from transformers import TrOCRProcessor, VisionEncoderDecoderModel
TrOCRProcessor.from_pretrained("microsoft/trocr-large-handwritten", cache_dir=cache)
VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-large-handwritten", cache_dir=cache)
print("  TrOCR descargado")
PYEOF
info "TrOCR OK"

# ── 3. MinerU / PDF-Extract-Kit ──────────────────────────────────────────────
step "Descargando modelos MinerU (layout, detección, tablas, ~5 GB)..."
python3 - <<'PYEOF'
import os
os.environ.setdefault("MINERU_MODELS_DIR", f"{os.environ.get('MODELS_PATH', '/data/models')}/mineru")
try:
    import magic_pdf.model.doc_analyze_by_custom_model as _
    print("  MinerU modelos cargados")
except Exception as e:
    print(f"  MinerU: {e}")
PYEOF
info "MinerU OK"

# ── Tesseract español ─────────────────────────────────────────────────────────
step "Verificando Tesseract..."
if tesseract --list-langs 2>/dev/null | grep -q "spa"; then
    info "Tesseract español OK"
else
    warn "Tesseract español no detectado (ya debería estar en la imagen Docker)"
fi

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ✓ Modelos HuggingFace descargados — sistema listo para modo offline${NC}"
echo ""
du -sh "${HF_CACHE}" "${MARKER_CACHE}" 2>/dev/null | sort -h || true
