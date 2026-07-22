#!/usr/bin/env bash
# =============================================================================
# build-bundle.sh — Arma el paquete offline completo (imágenes Docker, modelos
# IA, paquetes .deb) para copiar a un USB/disco y desplegar en una PC sin red.
#
# Corre esto en CUALQUIER máquina Ubuntu 24.04 (noble) x86_64 CON internet —
# no necesita GPU. Apunta el destino DIRECTAMENTE al USB/disco montado: el
# script trabaja ahí desde el inicio (no duplica ~45 GB en el disco local).
#
# Uso:
#   ./offline/build-bundle.sh /ruta/al/usb/ocr-agent-offline
#
# Salida (todo dentro de la ruta indicada):
#   ocr-agent-offline/
#   ├── ocr-agent/              ← copia del repo, con volumes/models ya poblado
#   ├── images/ocr-images.tar.gz
#   ├── packages/docker/*.deb
#   ├── packages/rocm/*.deb     (best-effort, puede quedar vacío)
#   └── MANIFEST.txt
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()   { echo -e "  ${RED}✗${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}▶${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
[[ -f "$SRC_REPO_DIR/docker-compose.yml" ]] || err "No se encontró docker-compose.yml junto a offline/ — corre esto desde el repo."

OUT="${1:-}"
[[ -n "$OUT" ]] || err "Uso: $0 /ruta/al/usb/ocr-agent-offline"
mkdir -p "$OUT"/{images,packages/docker,packages/rocm}
OUT="$(cd "$OUT" && pwd)"

FREE_KB=$(df -Pk "$OUT" | tail -1 | awk '{print $4}')
FREE_GB=$((FREE_KB / 1024 / 1024))
step "Destino: $OUT  (${FREE_GB} GB libres)"
[[ $FREE_GB -lt 45 ]] && warn "Menos de 45 GB libres en destino — el bundle puede no entrar (~45-55 GB)."

source /etc/os-release
[[ "${VERSION_CODENAME:-}" == "noble" ]] || warn "Este script se probó para Ubuntu 24.04 (noble). Detectado: ${VERSION_CODENAME:-desconocido}. Los .deb de docker/ROCm deben coincidir con el codename del DESTINO."

step "Verificando Docker en esta máquina puente..."
command -v docker &>/dev/null && docker compose version &>/dev/null \
    || err "Esta máquina puente necesita Docker Engine + compose plugin instalado y funcional antes de continuar."
info "Docker OK: $(docker --version)"

# ── 1. Copiar el repo al destino y trabajar ahí directamente ────────────────
step "Copiando repo a ${OUT}/ocr-agent (sin modelos aún, eso se descarga ahí mismo)..."
rsync -a \
    --exclude='.git' \
    --exclude='volumes/db/*.db*' \
    --exclude='volumes/output/*' \
    --exclude='volumes/originals/*' \
    "$SRC_REPO_DIR"/ "$OUT/ocr-agent/"
REPO_DIR="$OUT/ocr-agent"
cd "$REPO_DIR"
mkdir -p volumes/models/ollama volumes/models/huggingface volumes/models/marker \
         volumes/models/mineru volumes/models/torch volumes/db volumes/output \
         volumes/originals volumes/redis volumes/input
info "Repo copiado — trabajando desde ${REPO_DIR}"

# ── 2. Descargar .deb de Docker Engine para el DESTINO (sin red) ────────────
step "Descargando paquetes .deb de Docker Engine para el destino..."
if [[ ! -f /usr/share/keyrings/docker-archive-keyring.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update -qq
sudo apt-get clean   # caché limpio para que el cp de abajo no arrastre .deb de otros pasos
# --reinstall fuerza la descarga aunque el paquete ya esté instalado en esta
# máquina puente (si no, apt no descarga nada porque ya está "satisfecho").
sudo apt-get install -y --reinstall --download-only --no-install-recommends \
    docker-ce docker-ce-cli containerd.io docker-compose-plugin
cp /var/cache/apt/archives/*.deb "$OUT/packages/docker/" 2>/dev/null || true
info "$(ls "$OUT/packages/docker" | wc -l) paquetes .deb de Docker copiados"

# ── 3. ROCm para el DESTINO — best-effort, no aborta el bundle si falla ────
step "Intentando empaquetar ROCm (AMD GPU) — best-effort..."
(
    set -e
    CODENAME="$(lsb_release -cs)"
    ROCM_DEB="amdgpu-install_6.3.60300-1_all.deb"
    ROCM_URL="https://repo.radeon.com/amdgpu-install/6.3/ubuntu/${CODENAME}/${ROCM_DEB}"
    TMP_ROCM="$(mktemp -d)"
    curl -fsSL -o "${TMP_ROCM}/${ROCM_DEB}" "$ROCM_URL"
    cp "${TMP_ROCM}/${ROCM_DEB}" "$OUT/packages/rocm/"
    sudo apt-get install -y "${TMP_ROCM}/${ROCM_DEB}"
    sudo apt-get update -qq
    sudo apt-get clean   # caché limpio — que este cp no arrastre los .deb de docker del paso anterior
    sudo apt-get install -y --reinstall --download-only --no-install-recommends amdgpu-dkms rocm
    cp /var/cache/apt/archives/*.deb "$OUT/packages/rocm/" 2>/dev/null || true
    rm -rf "$TMP_ROCM"
) && info "Paquetes ROCm empaquetados (best-effort) — $(ls "$OUT/packages/rocm" | wc -l) archivos" \
  || warn "No se pudo empaquetar ROCm automáticamente. Si el destino ya tiene /dev/kfd (driver amdgpu ya cargado) no hace falta nada más. Si no, este bloque falló y habría que resolverlo con red temporal en destino."

# ── 4. Construir imagen backend/worker ───────────────────────────────────────
step "Construyendo imagen backend/worker (ocr-agent-backend:offline)..."
docker compose build backend worker
info "Imagen construida"

# ── 5. Pull de redis y ollama (tag ROCm, sirve también sin GPU) ─────────────
step "Descargando imágenes redis y ollama/ollama:rocm..."
docker compose pull redis ollama
info "Imágenes descargadas"

# ── 6. Modelos Ollama (qwen2.5:32b, minicpm-v) ───────────────────────────────
step "Descargando modelos Ollama (~24.5 GB) directo en ${REPO_DIR}/volumes/models/ollama..."
docker compose up -d ollama
MAX_WAIT=90; ELAPSED=0
# Chequeo DENTRO del contenedor (docker compose exec), no vía el puerto mapeado
# al host — en WSL2 el port-mapping a veces tarda o falla aunque el server ya
# esté sano por dentro.
until docker compose exec -T ollama curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    [[ $ELAPSED -ge $MAX_WAIT ]] && err "Ollama no respondió en ${MAX_WAIT}s (revisa: docker logs ocr-ollama)"
    sleep 3; ELAPSED=$((ELAPSED + 3))
done
docker compose exec ollama ollama pull qwen2.5:32b
docker compose exec ollama ollama pull minicpm-v
docker compose stop ollama
info "Modelos Ollama descargados"

# ── 7. Modelos HuggingFace / Surya / TrOCR / MinerU (~8 GB) ─────────────────
step "Descargando modelos HuggingFace (Surya, TrOCR, MinerU) directo en volumes/models/..."
docker compose run --rm --no-deps \
    -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 \
    worker bash /app/download_models.sh
info "Modelos HuggingFace descargados"

# ── 8. Exportar imágenes Docker directo al USB ───────────────────────────────
step "Exportando imágenes Docker a ${OUT}/images/ocr-images.tar.gz..."
docker save ocr-agent-backend:offline redis:7-alpine ollama/ollama:rocm \
    | gzip -1 > "$OUT/images/ocr-images.tar.gz"
info "Imágenes exportadas ($(du -sh "$OUT/images/ocr-images.tar.gz" | cut -f1))"

# ── 9. Manifiesto ─────────────────────────────────────────────────────────────
step "Generando MANIFEST.txt..."
{
    echo "OCR Agent — bundle offline"
    echo "Generado: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
    echo "Commit repo: $(git -C "$SRC_REPO_DIR" rev-parse HEAD 2>/dev/null || echo desconocido)"
    echo "Ubuntu codename origen: $(lsb_release -cs)"
    echo ""
    echo "-- Tamaños --"
    du -sh "$REPO_DIR"/volumes/models "$OUT"/images "$OUT"/packages 2>/dev/null
    echo ""
    echo "-- Checksum imágenes --"
    sha256sum "$OUT/images/ocr-images.tar.gz"
} > "$OUT/MANIFEST.txt"
info "MANIFEST.txt generado"

# ── 10. Limpieza de contenedores temporales en la puente ─────────────────────
docker compose down --remove-orphans 2>/dev/null || true

TOTAL=$(du -sh "$OUT" | cut -f1)
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║   Bundle offline listo — ${TOTAL}${NC}"
echo -e "${GREEN}  ╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}  ║  Ruta: ${OUT}${NC}"
echo -e "${GREEN}  ║                                                        ║${NC}"
echo -e "${GREEN}  ║  En el destino (sin red):                              ║${NC}"
echo -e "${GREEN}  ║    sudo ocr-agent/offline/install-target.sh            ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════╝${NC}"
