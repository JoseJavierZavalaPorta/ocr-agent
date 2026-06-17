#!/usr/bin/env bash
# =============================================================================
# install.sh — OCR Agent — Instalación Completa desde Cero
# Sistema operativo: Ubuntu 22.04 / 24.04 con GPU AMD (ROCm)
#
# Instala: Docker, Docker Compose, AMD ROCm, descarga modelos IA (~25 GB)
# y deja el sistema listo para ejecutar ./start.sh
#
# Uso:
#   chmod +x install.sh && ./install.sh
# =============================================================================
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "  ${GREEN}✓${NC} $*"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()     { echo -e "  ${RED}✗${NC} $*"; exit 1; }
step()    { echo -e "\n${BLUE}▶${NC} ${BOLD}$*${NC}"; }
substep() { echo -e "    ${CYAN}→${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Verificar que es Ubuntu ───────────────────────────────────────────────────
[[ -f /etc/os-release ]] && source /etc/os-release || true
if [[ "${ID:-}" != "ubuntu" ]]; then
    warn "Este script está diseñado para Ubuntu. Sistema detectado: ${PRETTY_NAME:-desconocido}"
    read -rp "  ¿Continuar de todas formas? [s/N] " choice
    [[ "${choice,,}" == "s" ]] || exit 1
fi

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║      OCR Agent — Instalación Completa               ║"
echo "  ║      Ubuntu + AMD ROCm                              ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "  Este proceso instalará (~35 GB de descarga):"
echo "    • Docker Engine + Docker Compose"
echo "    • AMD ROCm drivers (para GPU)"
echo "    • Modelo LLM:    qwen2.5:32b       (~19 GB) via Ollama"
echo "    • Modelo Vision: minicpm-v         (~5.5 GB) via Ollama"
echo "    • Surya + TrOCR + MinerU           (~8 GB)  via HuggingFace"
echo ""
read -rp "  ¿Continuar con la instalación? [s/N] " CONFIRM
[[ "${CONFIRM,,}" == "s" ]] || { echo "Cancelado."; exit 0; }

# ── 1. Dependencias base del sistema ─────────────────────────────────────────
step "Actualizando sistema e instalando dependencias base..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    curl wget git python3 python3-pip \
    apt-transport-https ca-certificates gnupg lsb-release \
    poppler-utils jq
info "Dependencias base instaladas"

# ── 2. Instalar Docker Engine ─────────────────────────────────────────────────
step "Instalando Docker Engine..."
if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version 2>/dev/null | grep -oP '\d+\.\d+' | head -1)
    info "Docker ya instalado: $(docker --version)"
else
    substep "Agregando repositorio oficial de Docker..."
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    info "Docker instalado: $(docker --version)"
fi

# Agregar usuario al grupo docker (evita usar sudo)
if ! groups "$USER" | grep -q docker; then
    sudo usermod -aG docker "$USER"
    warn "Usuario agregado al grupo 'docker'. Cierra sesión y vuelve a entrar, o ejecuta: newgrp docker"
fi

# ── 3. Verificar Docker Compose ───────────────────────────────────────────────
step "Verificando Docker Compose..."
if docker compose version &>/dev/null; then
    info "Docker Compose: $(docker compose version)"
else
    err "Docker Compose no disponible. Instala 'docker-compose-plugin'."
fi

# ── 4. Instalar AMD ROCm ──────────────────────────────────────────────────────
step "Verificando drivers AMD ROCm..."
if command -v rocminfo &>/dev/null; then
    # Herramientas de usuario ya instaladas
    info "ROCm ya instalado: $(rocminfo 2>/dev/null | grep 'ROCm Version' | head -1 || echo 'versión detectada')"
elif [[ -e /dev/kfd ]]; then
    # Driver AMD cargado en el kernel → Ollama accede a la GPU via Docker device passthrough.
    # No se necesita instalar ROCm en el host — el container de Ollama lo incluye.
    info "Driver AMD detectado (/dev/kfd) — ROCm funcional para Docker"
    warn "Herramientas de usuario (rocminfo) no instaladas en el host — no son necesarias"
else
    # Máquina sin driver AMD → instalar ROCm completo
    warn "GPU AMD no detectada (/dev/kfd ausente). Instalando ROCm..."
    echo ""
    read -rp "  ¿Instalar AMD ROCm ahora? (requiere internet, ~1 GB) [s/N] " ROCM_CONFIRM
    if [[ "${ROCM_CONFIRM,,}" == "s" ]]; then
        UBUNTU_VER=$(lsb_release -rs)
        CODENAME=$(lsb_release -cs)
        substep "Descargando instalador ROCm para Ubuntu ${UBUNTU_VER}..."

        ROCM_DEB="amdgpu-install_6.3.60300-1_all.deb"
        ROCM_URL="https://repo.radeon.com/amdgpu-install/6.3/ubuntu/${CODENAME}/${ROCM_DEB}"

        wget -q --show-progress -O /tmp/${ROCM_DEB} "${ROCM_URL}" \
            || { warn "No se pudo descargar ROCm para Ubuntu ${UBUNTU_VER}/${CODENAME}"; \
                 warn "Descarga manualmente desde: https://rocm.docs.amd.com/projects/install-on-linux/"; \
                 ROCM_SKIP=true; }

        if [[ "${ROCM_SKIP:-false}" != "true" ]]; then
            sudo apt-get install -y /tmp/${ROCM_DEB}
            sudo amdgpu-install --usecase=rocm --no-dkms -y
            info "ROCm instalado — reinicia el sistema para cargar el driver"
        fi
    else
        warn "ROCm omitido — Ollama correrá en CPU (más lento)"
    fi
fi

# Agregar usuario a grupos necesarios para AMD GPU
for grp in render video; do
    if getent group "$grp" &>/dev/null && ! groups "$USER" | grep -q "$grp"; then
        sudo usermod -aG "$grp" "$USER"
        substep "Usuario agregado al grupo '$grp'"
    fi
done

# ── 5. Crear estructura de directorios ────────────────────────────────────────
step "Creando estructura de directorios..."
mkdir -p volumes/input volumes/output volumes/originals \
         volumes/db volumes/redis \
         volumes/models/ollama volumes/models/huggingface \
         volumes/models/marker volumes/models/mineru volumes/models/torch

# Crear .gitkeep para que los directorios vacíos se trackeen en git
for d in volumes/input volumes/output volumes/originals volumes/db \
          volumes/redis volumes/models volumes/models/ollama volumes/models/huggingface; do
    touch "${d}/.gitkeep"
done
info "Directorios creados"

# ── 6. Crear .env desde .env.example ─────────────────────────────────────────
step "Configurando variables de entorno..."
if [[ ! -f .env ]]; then
    cp .env.example .env
    info ".env creado desde .env.example"
    echo ""
    echo -e "  ${YELLOW}IMPORTANTE: Ajusta la versión GFX de tu GPU en .env${NC}"
    echo -e "  Consulta con: ${CYAN}rocminfo | grep gfx${NC}"
    echo -e "  Ejemplos: RX 6000 → 10.3.0 | RX 7000 → 11.0.0 | RX 9000 → 12.0.0"
    echo ""
else
    info ".env ya existe — no se sobreescribe"
fi

# ── 7. Construir imágenes Docker ──────────────────────────────────────────────
step "Construyendo imágenes Docker (puede tardar 10-20 minutos la primera vez)..."
# Usar newgrp para que el grupo docker esté activo sin relogueo
if groups "$USER" | grep -q docker; then
    docker compose build
else
    sudo docker compose build
fi
info "Imágenes construidas"

# ── 8. Iniciar Ollama y descargar modelos IA ──────────────────────────────────
step "Iniciando Ollama y descargando modelos IA (~25 GB)..."
if groups "$USER" | grep -q docker; then
    docker compose up -d ollama
else
    sudo docker compose up -d ollama
fi

substep "Esperando que Ollama arranque..."
MAX_WAIT=90; ELAPSED=0
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
    [[ $ELAPSED -ge $MAX_WAIT ]] && err "Ollama no respondió en ${MAX_WAIT}s"
    sleep 3; ELAPSED=$((ELAPSED + 3))
done
info "Ollama listo"

# Función para descargar modelo con progreso
pull_model() {
    local model="$1"
    local size="$2"
    substep "Descargando ${model} (~${size})..."
    
    # Verificar si ya está descargado
    if curl -s http://localhost:11434/api/tags | grep -q "\"${model}\""; then
        info "${model} ya descargado"
        return
    fi
    
    docker compose exec ollama ollama pull "${model}"
    info "${model} descargado"
}

pull_model "qwen2.5:32b"  "19 GB"
pull_model "minicpm-v"    "5.5 GB"

# ── 9. Detener Ollama (se reiniciará con start.sh) ───────────────────────────
docker compose stop ollama 2>/dev/null || true

# ── 10. Descargar modelos HuggingFace (Surya, TrOCR, MinerU) ─────────────────
step "Descargando modelos HuggingFace (~8 GB: Surya, TrOCR, MinerU)..."
substep "Iniciando container worker temporalmente para la descarga..."

DOCKER_CMD="docker"
groups "$USER" | grep -q docker || DOCKER_CMD="sudo docker"

$DOCKER_CMD compose run --rm --no-deps \
    -e HF_HUB_OFFLINE=0 \
    -e TRANSFORMERS_OFFLINE=0 \
    worker bash /app/download_models.sh

info "Modelos HuggingFace descargados"

# ── 11. Verificación final ────────────────────────────────────────────────────
step "Verificando instalación..."
ERRORS=0

command -v docker &>/dev/null && info "Docker: OK" || { warn "Docker: NO encontrado"; ERRORS=$((ERRORS+1)); }
docker compose version &>/dev/null && info "Docker Compose: OK" || { warn "Docker Compose: NO encontrado"; ERRORS=$((ERRORS+1)); }
[[ -f .env ]] && info ".env: OK" || { warn ".env: NO existe"; ERRORS=$((ERRORS+1)); }
[[ -d volumes/input ]] && info "Directorios: OK" || { warn "Directorios: NO creados"; ERRORS=$((ERRORS+1)); }

if [[ $ERRORS -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}  ╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}  ║   Instalación completada con éxito                  ║${NC}"
    echo -e "${GREEN}  ╠══════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}  ║  Siguiente paso:                                     ║${NC}"
    echo -e "${GREEN}  ║                                                      ║${NC}"
    echo -e "${GREEN}  ║  1. Copia tus PDFs a: volumes/input/                ║${NC}"
    echo -e "${GREEN}  ║     O usa una ruta propia:                           ║${NC}"
    echo -e "${GREEN}  ║                                                      ║${NC}"
    echo -e "${GREEN}  ║  2. Ejecuta:  ./start.sh [ruta/a/documentos]        ║${NC}"
    echo -e "${GREEN}  ║     Ejemplo:  ./start.sh /home/usuario/documentos   ║${NC}"
    echo -e "${GREEN}  ║                                                      ║${NC}"
    echo -e "${GREEN}  ║  3. Si el sistema se apaga:  ./resume.sh            ║${NC}"
    echo -e "${GREEN}  ╚══════════════════════════════════════════════════════╝${NC}"
else
    echo ""
    echo -e "${YELLOW}  Instalación completada con ${ERRORS} advertencia(s).${NC}"
    echo -e "  Revisa los mensajes anteriores y corrige los problemas."
fi

if ! groups "$USER" | grep -q docker; then
    echo ""
    warn "IMPORTANTE: Cierra sesión y vuelve a entrar para que los cambios"
    warn "de grupo (docker, render, video) tomen efecto, o ejecuta:"
    echo -e "  ${CYAN}  newgrp docker${NC}"
fi
echo ""
