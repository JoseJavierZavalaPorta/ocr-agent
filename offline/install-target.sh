#!/usr/bin/env bash
# =============================================================================
# install-target.sh — Instala OCR Agent en la PC destino SIN conexión a red.
#
# Reemplaza a install.sh cuando no hay internet: en vez de descargar todo,
# usa lo que build-bundle.sh ya dejó en el USB junto a este repo:
#   ocr-agent-offline/
#   ├── ocr-agent/           ← este repo (donde vive este script)
#   ├── images/ocr-images.tar.gz
#   └── packages/{docker,rocm}/*.deb
#
# Uso (un solo comando, sin pasos manuales):
#   sudo ./offline/install-target.sh
#
# Detecta automáticamente si hay GPU AMD (/dev/kfd) y arma el docker compose
# con o sin el override de GPU según corresponda.
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()   { echo -e "  ${RED}✗${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}▶${NC} $*"; }

[[ $EUID -eq 0 ]] || err "Corre este script con sudo: sudo $0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUNDLE_ROOT="$(cd "$REPO_DIR/.." && pwd)"
IMAGES_TAR="$BUNDLE_ROOT/images/ocr-images.tar.gz"
DEB_DOCKER="$BUNDLE_ROOT/packages/docker"
DEB_ROCM="$BUNDLE_ROOT/packages/rocm"

[[ -f "$IMAGES_TAR" ]] || err "No se encontró $IMAGES_TAR — este script debe correr dentro del bundle generado por build-bundle.sh."

REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║      OCR Agent — Instalación Offline (sin red)       ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. Docker Engine ──────────────────────────────────────────────────────────
step "Verificando Docker Engine..."
if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    info "Docker ya instalado: $(docker --version)"
else
    [[ -d "$DEB_DOCKER" ]] && [[ -n "$(ls -A "$DEB_DOCKER" 2>/dev/null)" ]] \
        || err "No hay paquetes .deb en $DEB_DOCKER — no se puede instalar Docker sin red."
    step "Instalando Docker Engine desde paquetes locales..."
    apt-get install -y "$DEB_DOCKER"/*.deb
    info "Docker instalado: $(docker --version)"
fi

if ! groups "$REAL_USER" | grep -q docker; then
    usermod -aG docker "$REAL_USER"
    info "Usuario '$REAL_USER' agregado al grupo docker (efectivo tras relogin — este script sigue usando root mientras tanto)"
fi

# ── 2. GPU — detecta NVIDIA primero, luego AMD, si no CPU ────────────────────
step "Verificando GPU..."
HAS_GPU=0
GPU_VENDOR=""

if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    info "GPU NVIDIA detectada: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
    if command -v nvidia-ctk &>/dev/null || dpkg -l nvidia-container-toolkit &>/dev/null 2>&1; then
        info "nvidia-container-toolkit ya instalado"
    else
        warn "nvidia-container-toolkit no instalado — intentando instalarlo (necesita red)..."
        if apt-get install -y nvidia-container-toolkit 2>/dev/null; then
            nvidia-ctk runtime configure --runtime=docker
            systemctl restart docker
            info "nvidia-container-toolkit instalado y configurado"
        else
            warn "No se pudo instalar nvidia-container-toolkit (¿sin red y sin paquete local?). El sistema correrá en CPU."
        fi
    fi
    if command -v nvidia-ctk &>/dev/null; then
        HAS_GPU=1
        GPU_VENDOR="nvidia"
    fi
elif [[ -e /dev/kfd ]]; then
    info "/dev/kfd presente — GPU AMD lista para pasar al contenedor de Ollama"
    HAS_GPU=1
    GPU_VENDOR="amd"
elif [[ -d "$DEB_ROCM" ]] && [[ -n "$(ls -A "$DEB_ROCM" 2>/dev/null)" ]]; then
    warn "/dev/kfd no existe — intentando instalar ROCm desde paquetes locales (best-effort)..."
    if apt-get install -y "$DEB_ROCM"/*.deb 2>/dev/null; then
        if [[ -e /dev/kfd ]]; then
            info "ROCm instalado y /dev/kfd disponible"
            HAS_GPU=1
            GPU_VENDOR="amd"
        else
            warn "ROCm instalado pero /dev/kfd sigue sin aparecer — probablemente falta reiniciar el equipo para cargar el driver amdgpu. Corre este script de nuevo después de reiniciar."
        fi
    else
        warn "No se pudo instalar ROCm desde los paquetes locales. El sistema seguirá funcionando en modo CPU."
    fi
else
    warn "No se detectó GPU AMD ni NVIDIA — el sistema correrá en CPU (más lento pero funcional)."
fi

# ── 3. Cargar imágenes Docker ─────────────────────────────────────────────────
step "Cargando imágenes Docker desde ${IMAGES_TAR}..."
gunzip -c "$IMAGES_TAR" | docker load
info "Imágenes cargadas"

# ── 4. Configuración (.env) ───────────────────────────────────────────────────
cd "$REPO_DIR"
if [[ ! -f .env ]]; then
    cp .env.example .env
    warn ".env creado desde .env.example — ajusta HSA_OVERRIDE_GFX_VERSION si tienes GPU AMD (rocminfo | grep gfx)"
fi
if [[ "$GPU_VENDOR" == "amd" ]] && ! grep -q "^OLLAMA_IMAGE=" .env; then
    echo "OLLAMA_IMAGE=ollama/ollama:rocm" >> .env
fi
chown -R "$REAL_USER":"$REAL_USER" "$REPO_DIR" 2>/dev/null || true

mkdir -p volumes/db volumes/output volumes/originals volumes/redis \
         volumes/input volumes/models/ollama volumes/models/huggingface \
         volumes/models/marker volumes/models/mineru volumes/models/torch

# ── 5. Levantar servicios (con el override de GPU que corresponda) ───────────
step "Levantando servicios..."
COMPOSE_ARGS=(-f docker-compose.yml)
if [[ "${HAS_GPU:-0}" == "1" && "$GPU_VENDOR" == "nvidia" ]]; then
    COMPOSE_ARGS+=(-f docker-compose.gpu-nvidia.yml)
elif [[ "${HAS_GPU:-0}" == "1" && "$GPU_VENDOR" == "amd" ]]; then
    COMPOSE_ARGS+=(-f docker-compose.gpu.yml)
fi

sudo -u "$REAL_USER" docker compose "${COMPOSE_ARGS[@]}" up -d
info "Servicios levantados"

# ── 6. Verificación ────────────────────────────────────────────────────────────
step "Esperando que el backend responda..."
MAX_WAIT=120; ELAPSED=0
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    [[ $ELAPSED -ge $MAX_WAIT ]] && { warn "Backend sin respuesta en ${MAX_WAIT}s — revisa: docker compose logs backend"; break; }
    sleep 3; ELAPSED=$((ELAPSED + 3))
done
[[ $ELAPSED -lt $MAX_WAIT ]] && info "Backend OK (${ELAPSED}s)"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║   Instalación offline completada                    ║${NC}"
echo -e "${GREEN}  ╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}  ║  API:  http://localhost:8000/docs                    ║${NC}"
echo -e "${GREEN}  ║                                                        ║${NC}"
echo -e "${GREEN}  ║  Cierra sesión y vuelve a entrar (o newgrp docker)     ║${NC}"
echo -e "${GREEN}  ║  para usar ./start.sh sin sudo.                        ║${NC}"
echo -e "${GREEN}  ║                                                        ║${NC}"
echo -e "${GREEN}  ║  Siguiente paso:                                       ║${NC}"
echo -e "${GREEN}  ║    cd ocr-agent && ./start.sh /ruta/a/documentos       ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════════╝${NC}"
if [[ "${HAS_GPU:-0}" == "1" ]]; then
    echo ""
    echo "  Verifica que Ollama detectó la GPU:"
    echo "    docker logs ocr-ollama | grep -i 'inference compute'"
fi
