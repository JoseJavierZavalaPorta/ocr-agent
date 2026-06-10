#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — OCR Agent
# Prepara una máquina Ubuntu limpia desde cero y despliega el sistema.
#
# Uso en la máquina destino (una sola vez, con internet):
#   curl -fsSL https://raw.githubusercontent.com/JoseJavierZavalaPorta/ocr-agent/main/bootstrap.sh -o bootstrap.sh
#   chmod +x bootstrap.sh && ./bootstrap.sh
#
# El script es reentrant: si se interrumpe o necesita reinicio,
# vuelve a ejecutarlo y continúa desde donde quedó.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
err()   { echo -e "${RED}  ✗${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}━━━ $* ${NC}"; }
title() { echo -e "\n${CYAN}$*${NC}"; }

STATE_FILE="$HOME/.ocr_bootstrap_state"
REPO_URL="https://github.com/JoseJavierZavalaPorta/ocr-agent.git"
INSTALL_DIR="$HOME/ocr-agent"

# Leer estado previo
declare -A STATE=()
if [ -f "$STATE_FILE" ]; then
    while IFS='=' read -r k v; do
        STATE["$k"]="$v"
    done < "$STATE_FILE"
fi

save_state() { echo "$1=$2" >> "$STATE_FILE"; STATE["$1"]="$2"; }
done_step()  { [[ "${STATE[$1]:-}" == "done" ]]; }

# ─────────────────────────────────────────────────────────────────────────────

title "╔══════════════════════════════════════════════════════╗"
title "║        OCR Agent — Bootstrap Automático             ║"
title "║  Máquina: $(hostname)   Usuario: $USER              ║"
title "╚══════════════════════════════════════════════════════╝"

# Verificar OS
if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
    warn "Este script está probado en Ubuntu 22.04/24.04. Continúa bajo tu responsabilidad."
fi

UBUNTU_VERSION=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2)
info "Sistema: Ubuntu $UBUNTU_VERSION"

# ── FASE 1: Dependencias base ─────────────────────────────────────────────────
step "FASE 1 — Dependencias del sistema"

if ! done_step "apt_base"; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        git curl wget gnupg2 ca-certificates lsb-release \
        software-properties-common apt-transport-https \
        pciutils usbutils 2>/dev/null
    save_state "apt_base" "done"
    info "Paquetes base instalados"
else
    info "Paquetes base (ya instalados)"
fi

# ── FASE 2: Docker ────────────────────────────────────────────────────────────
step "FASE 2 — Docker + Docker Compose v2"

if ! done_step "docker"; then
    if command -v docker &>/dev/null; then
        DOCKER_VER=$(docker --version | grep -oP '\d+\.\d+' | head -1)
        info "Docker ya instalado: $DOCKER_VER"
    else
        info "Instalando Docker..."
        curl -fsSL https://get.docker.com | sudo sh
        info "Docker instalado"
    fi

    # Añadir usuario al grupo docker
    if ! groups "$USER" | grep -q docker; then
        sudo usermod -aG docker "$USER"
        warn "Usuario añadido al grupo docker (efectivo tras reinicio o nueva sesión)"
    else
        info "Usuario ya en grupo docker"
    fi

    # Verificar Docker Compose v2
    if ! docker compose version &>/dev/null; then
        sudo apt-get install -y docker-compose-plugin
    fi

    save_state "docker" "done"
    info "Docker Compose: $(docker compose version --short 2>/dev/null || echo 'ok')"
else
    info "Docker (ya instalado)"
fi

# ── FASE 3: ROCm AMD ──────────────────────────────────────────────────────────
step "FASE 3 — Driver AMD ROCm"

if ! done_step "rocm"; then
    if [ -c "/dev/kfd" ]; then
        info "ROCm ya instalado (/dev/kfd presente)"
        save_state "rocm" "done"
    else
        # Detectar GPU AMD
        GPU_INFO=$(lspci 2>/dev/null | grep -i "VGA\|Display\|3D" | grep -i "AMD\|ATI\|Radeon" || echo "")
        if [ -z "$GPU_INFO" ]; then
            warn "No se detectó GPU AMD con lspci. Instalando ROCm de todas formas..."
        else
            info "GPU AMD detectada: $GPU_INFO"
        fi

        # Determinar codename de Ubuntu para la URL
        UBUNTU_CODENAME=$(lsb_release -cs)
        case "$UBUNTU_CODENAME" in
            jammy)   ROCM_DISTRO="jammy" ;;
            noble)   ROCM_DISTRO="noble" ;;
            focal)   ROCM_DISTRO="focal" ;;
            *)       ROCM_DISTRO="jammy"; warn "Ubuntu $UBUNTU_CODENAME no verificado, usando jammy" ;;
        esac

        info "Descargando instalador ROCm 6.2 para $UBUNTU_CODENAME..."
        ROCM_DEB="amdgpu-install_6.2.60200-1_all.deb"
        ROCM_URL="https://repo.radeon.com/amdgpu-install/6.2/ubuntu/${ROCM_DISTRO}/${ROCM_DEB}"

        wget -q --show-progress "$ROCM_URL" -O "/tmp/$ROCM_DEB"
        sudo apt-get install -y "/tmp/$ROCM_DEB"
        sudo amdgpu-install -y --usecase=rocm,opencl,hip --no-dkms 2>&1 | tail -5

        # Grupos GPU
        sudo usermod -aG render,video "$USER"

        save_state "rocm" "done"
        save_state "needs_reboot" "yes"
        info "ROCm instalado. Se requiere reinicio."
    fi
else
    info "ROCm (ya instalado)"
fi

# Grupos GPU (idempotente)
if ! groups "$USER" | grep -q render; then
    sudo usermod -aG render,video "$USER"
    save_state "needs_reboot" "yes"
    warn "Añadido a grupos render/video — requiere reinicio"
fi

# ── FASE 4: Verificar reinicio si es necesario ────────────────────────────────
if [[ "${STATE[needs_reboot]:-}" == "yes" ]] && [ ! -c "/dev/kfd" ]; then
    echo ""
    echo -e "${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  ⚡ REINICIO REQUERIDO                                   ║${NC}"
    echo -e "${YELLOW}║                                                          ║${NC}"
    echo -e "${YELLOW}║  El driver ROCm necesita reiniciar el sistema.           ║${NC}"
    echo -e "${YELLOW}║                                                          ║${NC}"
    echo -e "${YELLOW}║  Después del reinicio, ejecuta de nuevo:                 ║${NC}"
    echo -e "${YELLOW}║    ./bootstrap.sh                                        ║${NC}"
    echo -e "${YELLOW}║                                                          ║${NC}"
    echo -e "${YELLOW}║  El script continuará automáticamente desde aquí.        ║${NC}"
    echo -e "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    read -p "¿Reiniciar ahora? [S/n]: " DO_REBOOT
    DO_REBOOT=${DO_REBOOT:-S}
    if [[ "$DO_REBOOT" =~ ^[Ss]$ ]]; then
        sudo reboot
    else
        warn "Reinicia manualmente y vuelve a ejecutar ./bootstrap.sh"
        exit 0
    fi
fi

# ── FASE 5: Detectar GFX version ─────────────────────────────────────────────
step "FASE 5 — Detectar versión GFX de la GPU"

if ! done_step "gfx_detect"; then
    GFX_VER=""

    if command -v rocminfo &>/dev/null; then
        GFX_RAW=$(rocminfo 2>/dev/null | grep -oP 'gfx\K[0-9a-f]+' | head -1 || echo "")
        if [ -n "$GFX_RAW" ]; then
            # gfx1200 → 12.0.0
            LEN=${#GFX_RAW}
            if [ "$LEN" -ge 4 ]; then
                MAJOR="${GFX_RAW:0:$((LEN-2))}"
                MINOR="${GFX_RAW:$((LEN-2)):1}"
                PATCH="${GFX_RAW:$((LEN-1)):1}"
                GFX_VER="${MAJOR}.${MINOR}.${PATCH}"
            fi
        fi
    fi

    # Fallback por nombre de GPU
    if [ -z "$GFX_VER" ]; then
        GPU_NAME=$(lspci 2>/dev/null | grep -i "AMD\|Radeon" | grep -i "VGA\|Display" | head -1 || echo "")
        if echo "$GPU_NAME" | grep -qiE "5090|9070|9060|RDNA.?4"; then
            GFX_VER="12.0.0"
            warn "GPU RDNA4 detectada por nombre — usando GFX 12.0.0"
        elif echo "$GPU_NAME" | grep -qiE "7900|7800|7700|7600|RDNA.?3"; then
            GFX_VER="11.0.0"
            warn "GPU RDNA3 detectada por nombre — usando GFX 11.0.0"
        elif echo "$GPU_NAME" | grep -qiE "6900|6800|6700|6600|RDNA.?2"; then
            GFX_VER="10.3.0"
            warn "GPU RDNA2 detectada por nombre — usando GFX 10.3.0"
        else
            GFX_VER="11.0.0"
            warn "No se pudo detectar GFX version automáticamente. Usando 11.0.0 como default."
            warn "Si hay errores GPU, edita .env y ajusta HSA_OVERRIDE_GFX_VERSION"
        fi
    fi

    save_state "gfx_version" "$GFX_VER"
    save_state "gfx_detect" "done"
    info "HSA_OVERRIDE_GFX_VERSION = $GFX_VER"
else
    GFX_VER="${STATE[gfx_version]:-11.0.0}"
    info "GFX version (ya detectada): $GFX_VER"
fi

# ── FASE 6: Clonar o actualizar el repositorio ────────────────────────────────
step "FASE 6 — Repositorio OCR Agent"

if [ -d "$INSTALL_DIR/.git" ]; then
    info "Repositorio ya existe en $INSTALL_DIR — actualizando..."
    git -C "$INSTALL_DIR" pull --rebase
else
    info "Clonando repositorio..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

info "Repositorio listo en: $INSTALL_DIR"

# ── FASE 7: Configurar .env ───────────────────────────────────────────────────
step "FASE 7 — Configuración .env"

cd "$INSTALL_DIR"

if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Creado .env desde .env.example"
fi

# Inyectar GFX version detectada
sed -i "s|^HSA_OVERRIDE_GFX_VERSION=.*|HSA_OVERRIDE_GFX_VERSION=${GFX_VER}|" .env
info "HSA_OVERRIDE_GFX_VERSION=${GFX_VER} escrito en .env"

save_state "env_configured" "done"

# ── FASE 8: Crear directorios de volumen ──────────────────────────────────────
step "FASE 8 — Directorios de datos"

for dir in volumes/input volumes/output volumes/originals volumes/db volumes/redis \
           volumes/models/ollama volumes/models/huggingface volumes/models/marker \
           volumes/models/mineru volumes/models/torch; do
    mkdir -p "$dir"
done
info "Directorios de volumen listos"

# ── FASE 9: Build y levantar servicios ───────────────────────────────────────
step "FASE 9 — Build y arranque de servicios Docker"

# Activar docker sin sudo para este proceso (si el grupo acaba de añadirse)
if ! docker info &>/dev/null 2>&1; then
    warn "Docker requiere nueva sesión para los permisos de grupo."
    warn "Ejecutando con sg docker..."
    exec sg docker -c "bash $(realpath "$0")"
fi

info "Descargando imagen Redis..."
docker compose pull redis --quiet

info "Construyendo imágenes del proyecto..."
docker compose build --parallel

info "Levantando todos los servicios..."
docker compose up -d

# Esperar health checks
wait_healthy() {
    local name=$1 max=${2:-90} elapsed=0
    echo -n "  Esperando $name"
    while [ $elapsed -lt $max ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "starting")
        [ "$status" = "healthy" ] && { echo " ✓"; return 0; }
        echo -n "."; sleep 3; elapsed=$((elapsed+3))
    done
    echo " (timeout — continúa de todas formas)"
}

wait_healthy ocr-redis 60
wait_healthy ocr-ollama 120
wait_healthy ocr-backend 90

save_state "services_up" "done"

# ── FASE 10: Descarga de modelos ──────────────────────────────────────────────
step "FASE 10 — Descarga de modelos OCR (~18 GB)"

echo ""
echo -e "  ${YELLOW}Esta es la ÚNICA vez que se necesita internet.${NC}"
echo -e "  Una vez descargados, el sistema opera completamente offline."
echo ""
echo -e "  Modelos a descargar:"
echo -e "    • Surya OCR (detección + reconocimiento)  ~3 GB"
echo -e "    • Surya Layout (tablas, columnas)          ~2 GB"
echo -e "    • TrOCR large handwritten (manuscritos)    ~2 GB"
echo -e "    • llama3.1:8b via Ollama (corrección IA)  ~5 GB"
echo -e "    • MinerU (tablas complejas)                ~4 GB"
echo -e "    • Tesseract español                        ~50 MB"
echo ""

read -p "  ¿Descargar modelos ahora? [S/n]: " DL
DL=${DL:-S}

if [[ "$DL" =~ ^[Ss]$ ]]; then
    docker compose exec worker bash /app/download_models.sh
    save_state "models_downloaded" "done"
    info "Modelos descargados. El sistema opera offline a partir de ahora."
else
    warn "Modelos no descargados."
    warn "Cuando tengas internet, ejecuta:"
    warn "  cd $INSTALL_DIR && docker compose exec worker bash /app/download_models.sh"
fi

# ── Resumen final ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           ✓ OCR Agent instalado y funcionando            ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}║  Frontend:    http://localhost:3000                       ║${NC}"
echo -e "${GREEN}║  API docs:    http://localhost:8000/docs                  ║${NC}"
echo -e "${GREEN}║  GPU:         HSA_GFX = ${GFX_VER}                       ║${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}║  Carpeta entrada:   $INSTALL_DIR/volumes/input/  ║${NC}"
echo -e "${GREEN}║  Carpeta salida:    $INSTALL_DIR/volumes/output/ ║${NC}"
echo -e "${GREEN}║                                                           ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Para ver logs:  docker compose logs -f worker           ║${NC}"
echo -e "${GREEN}║  Para detener:   docker compose down                     ║${NC}"
echo -e "${GREEN}║  Para iniciar:   docker compose up -d                    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Limpiar estado (instalación completa)
rm -f "$STATE_FILE"
