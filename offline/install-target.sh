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

# ── 2. GPU AMD — ROCm best-effort si /dev/kfd no existe ──────────────────────
step "Verificando GPU AMD..."
if [[ -e /dev/kfd ]]; then
    info "/dev/kfd presente — GPU AMD lista para pasar al contenedor de Ollama"
    HAS_GPU=1
elif [[ -d "$DEB_ROCM" ]] && [[ -n "$(ls -A "$DEB_ROCM" 2>/dev/null)" ]]; then
    warn "/dev/kfd no existe — intentando instalar ROCm desde paquetes locales (best-effort)..."
    if apt-get install -y "$DEB_ROCM"/*.deb 2>/dev/null; then
        if [[ -e /dev/kfd ]]; then
            info "ROCm instalado y /dev/kfd disponible"
            HAS_GPU=1
        else
            warn "ROCm instalado pero /dev/kfd sigue sin aparecer — probablemente falta reiniciar el equipo para cargar el driver amdgpu. Corre este script de nuevo después de reiniciar."
            HAS_GPU=0
        fi
    else
        warn "No se pudo instalar ROCm desde los paquetes locales. El sistema seguirá funcionando en modo CPU."
        HAS_GPU=0
    fi
else
    warn "/dev/kfd no existe y no hay paquetes ROCm en el bundle — el sistema correrá en CPU (más lento pero funcional)."
    HAS_GPU=0
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
chown -R "$REAL_USER":"$REAL_USER" "$REPO_DIR" 2>/dev/null || true

mkdir -p volumes/db volumes/output volumes/originals volumes/redis \
         volumes/input volumes/models/ollama volumes/models/huggingface \
         volumes/models/marker volumes/models/mineru volumes/models/torch

# ── 5. Levantar servicios (con o sin override de GPU) ─────────────────────────
step "Levantando servicios..."
COMPOSE_ARGS=(-f docker-compose.yml)
[[ "${HAS_GPU:-0}" == "1" ]] && COMPOSE_ARGS+=(-f docker-compose.gpu.yml)

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
