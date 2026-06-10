#!/usr/bin/env bash
# =============================================================================
# setup.sh — OCR Agent
# Un solo comando para levantar todo el sistema en la máquina destino.
# Uso: git clone <repo> && cd ocr-agent && ./setup.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()   { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
error_() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()   { echo -e "\n${BLUE}▶ $*${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       OCR Agent — Setup Automático       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Verificar prerrequisitos ───────────────────────────────────────────────
step "Verificando prerrequisitos..."

# Docker
if ! command -v docker &> /dev/null; then
    warn "Docker no encontrado. Instalando..."
    if command -v apt-get &> /dev/null; then
        curl -fsSL https://get.docker.com | sudo sh
        sudo usermod -aG docker "$USER"
        warn "Docker instalado. REINICIA la sesión y vuelve a ejecutar setup.sh si hay errores de permisos."
    else
        error_ "Instala Docker manualmente: https://docs.docker.com/get-docker/"
    fi
fi

DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+' | head -1)
info "Docker: $DOCKER_VERSION"

# Docker Compose v2
if ! docker compose version &> /dev/null; then
    error_ "Docker Compose v2 requerido. Actualiza Docker Desktop o instala el plugin."
fi
COMPOSE_VERSION=$(docker compose version --short)
info "Docker Compose: $COMPOSE_VERSION"

# ── 2. Detectar GPU AMD (ROCm) ────────────────────────────────────────────────
step "Detectando GPU AMD..."

GPU_MODE="cpu"
HSA_GFX=""

if [ -c "/dev/kfd" ] && [ -d "/dev/dri" ]; then
    GPU_MODE="rocm"
    info "✓ ROCm detectado (/dev/kfd presente)"

    # Detectar GFX version
    if command -v rocminfo &> /dev/null; then
        HSA_GFX=$(rocminfo 2>/dev/null | grep -oP 'gfx\K[0-9a-f]+' | head -1 || echo "")
        if [ -n "$HSA_GFX" ]; then
            # Convertir formato: 1200 → 12.0.0
            GFX_MAJOR="${HSA_GFX:0:-2}"
            GFX_MINOR="${HSA_GFX: -2:1}"
            GFX_PATCH="${HSA_GFX: -1}"
            HSA_GFX_VERSION="${GFX_MAJOR}.${GFX_MINOR}.${GFX_PATCH}"
            info "GFX detectado: gfx${HSA_GFX} → HSA_OVERRIDE_GFX_VERSION=${HSA_GFX_VERSION}"
        fi
    else
        # Para RX 5090 (RDNA4) asumir 12.0.0 si no se puede detectar
        GPU_INFO=$(lspci 2>/dev/null | grep -i "radeon\|amdgpu" | head -1 || echo "")
        if echo "$GPU_INFO" | grep -qi "5090\|9070\|9060"; then
            HSA_GFX_VERSION="12.0.0"
            warn "GPU RDNA4 detectada — usando HSA_OVERRIDE_GFX_VERSION=12.0.0"
        else
            warn "No se pudo detectar GFX version. El .env.example tiene 12.0.0 para RX 5090."
        fi
    fi
else
    warn "ROCm no detectado (/dev/kfd ausente). El sistema correrá en modo CPU."
    warn "En la máquina con RX 5090, asegúrate de tener instalado el driver ROCm."
    GPU_MODE="cpu"
fi

# ── 3. Configurar .env ────────────────────────────────────────────────────────
step "Configurando variables de entorno..."

if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Creado .env desde .env.example"
else
    info ".env ya existe, no se sobrescribe"
fi

# Actualizar HSA_OVERRIDE_GFX_VERSION si se detectó
if [ -n "${HSA_GFX_VERSION:-}" ]; then
    sed -i "s|^HSA_OVERRIDE_GFX_VERSION=.*|HSA_OVERRIDE_GFX_VERSION=${HSA_GFX_VERSION}|" .env
    info "HSA_OVERRIDE_GFX_VERSION=${HSA_GFX_VERSION} actualizado en .env"
fi

# ── 4. Crear directorios de volumen ───────────────────────────────────────────
step "Creando directorios de datos..."
for dir in volumes/input volumes/output volumes/originals volumes/db volumes/redis \
           volumes/models/ollama volumes/models/huggingface volumes/models/marker \
           volumes/models/mineru volumes/models/torch; do
    mkdir -p "$dir"
done
info "Directorios de volumen listos"

# ── 5. Ajustar docker-compose según GPU mode ──────────────────────────────────
if [ "$GPU_MODE" = "cpu" ]; then
    step "Modo CPU: ajustando docker-compose para omitir ROCm..."
    # En modo CPU, el worker y ollama no necesitan los devices
    # Usar override file
    cat > docker-compose.override.yml <<'OVERRIDE'
services:
  worker:
    devices: []
    group_add: []
  ollama:
    image: ollama/ollama:latest
    devices: []
    group_add: []
OVERRIDE
    warn "docker-compose.override.yml creado para modo CPU (solo para testing)"
fi

# ── 6. Build + Pull ───────────────────────────────────────────────────────────
step "Descargando imágenes Docker (puede tardar)..."
docker compose pull redis

step "Construyendo imágenes del proyecto..."
docker compose build --parallel

# ── 7. Levantar servicios ─────────────────────────────────────────────────────
step "Levantando servicios..."
docker compose up -d

# ── 8. Esperar health checks ──────────────────────────────────────────────────
step "Esperando que los servicios estén listos..."

wait_healthy() {
    local container=$1
    local max_wait=${2:-120}
    local elapsed=0
    while [ $elapsed -lt $max_wait ]; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "starting")
        if [ "$status" = "healthy" ]; then
            info "✓ $container listo"
            return 0
        fi
        echo -n "."
        sleep 3
        elapsed=$((elapsed + 3))
    done
    warn "$container no alcanzó estado healthy en ${max_wait}s — continuando de todas formas"
}

echo -n "  Redis"
wait_healthy ocr-redis 60
echo -n "  Ollama"
wait_healthy ocr-ollama 120
echo -n "  Backend"
wait_healthy ocr-backend 90

# ── 9. Descargar modelos (primera vez) ────────────────────────────────────────
echo ""
read -p "$(echo -e "${YELLOW}¿Descargar modelos ahora? (requiere internet) [S/n]: ${NC}")" DOWNLOAD_MODELS
DOWNLOAD_MODELS=${DOWNLOAD_MODELS:-S}

if [[ "$DOWNLOAD_MODELS" =~ ^[Ss]$ ]]; then
    step "Descargando modelos OCR (~18GB total, puede tardar 20-60 min)..."
    docker compose exec worker bash /app/download_models.sh
    info "✓ Modelos descargados. El sistema opera offline a partir de ahora."
else
    warn "Modelos no descargados. Ejecuta manualmente cuando tengas internet:"
    warn "  docker compose exec worker bash /app/download_models.sh"
fi

# ── 10. Resumen final ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           OCR Agent — Sistema listo             ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Frontend:  http://localhost:3000                ║${NC}"
echo -e "${GREEN}║  API:       http://localhost:8000/docs           ║${NC}"
echo -e "${GREEN}║  Ollama:    http://localhost:11434               ║${NC}"
echo -e "${GREEN}║  GPU mode:  ${GPU_MODE}                               ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Carpeta de entrada:  ./volumes/input/           ║${NC}"
echo -e "${GREEN}║  Carpeta de salida:   ./volumes/output/          ║${NC}"
echo -e "${GREEN}║  Originales:          ./volumes/originals/       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Logs: ${BLUE}docker compose logs -f worker${NC}"
echo -e "Stop: ${BLUE}docker compose down${NC}"
echo ""
