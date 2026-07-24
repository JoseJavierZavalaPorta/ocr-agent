#!/usr/bin/env bash
# =============================================================================
# start.sh — OCR Agent
# Levanta el sistema desde cero y encola todos los PDFs del directorio de input.
#
# Uso:
#   ./start.sh                                          # ./volumes/input -> ./volumes/output
#   ./start.sh /ruta/a/mis/documentos                    # input custom, output por defecto
#   ./start.sh /ruta/a/mis/documentos /ruta/de/salida    # input y output custom
# =============================================================================
set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "  ${GREEN}✓${NC} $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $*"; }
err()   { echo -e "  ${RED}✗${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}▶${NC} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Directorio de input / output (argumentos opcionales) ─────────────────────
INPUT_ARG="${1:-}"
if [[ -n "$INPUT_ARG" ]]; then
    INPUT_DIR="$(realpath "$INPUT_ARG")"
    [[ -d "$INPUT_DIR" ]] || err "El directorio no existe: $INPUT_DIR"
else
    INPUT_DIR="$(realpath ./volumes/input)"
fi
export INPUT_DIR

OUTPUT_ARG="${2:-}"
if [[ -n "$OUTPUT_ARG" ]]; then
    mkdir -p "$OUTPUT_ARG"
    OUTPUT_DIR="$(realpath "$OUTPUT_ARG")"
else
    OUTPUT_DIR="$(realpath ./volumes/output)"
fi
export OUTPUT_DIR

echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║         OCR Agent — Inicio Limpio             ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Input:  ${CYAN}${INPUT_DIR}${NC}"
echo -e "  Output: ${CYAN}${OUTPUT_DIR}${NC}"

# ── 1. Verificar .env ─────────────────────────────────────────────────────────
[[ -f .env ]] || { cp .env.example .env; warn ".env creado desde .env.example — revisa la configuración"; }

# ── 2. Detener contenedores existentes ───────────────────────────────────────
step "Deteniendo servicios existentes..."
docker compose down --remove-orphans 2>/dev/null && info "Servicios detenidos" || info "No había servicios activos"

# ── 3. Limpiar datos anteriores ───────────────────────────────────────────────
step "Limpiando base de datos, outputs y originales..."
rm -f volumes/db/ocr.db volumes/db/ocr.db-shm volumes/db/ocr.db-wal
rm -f "${OUTPUT_DIR}"/*.md "${OUTPUT_DIR}"/*_reporte.txt "${OUTPUT_DIR}/reporte_clasificacion.xlsx" 2>/dev/null || true
rm -f volumes/originals/*.pdf 2>/dev/null || true
info "Base de datos limpia"
info "Outputs limpiados"
info "Originales limpiados"

# ── 4. Verificar PDFs en el input ────────────────────────────────────────────
step "Verificando documentos en ${INPUT_DIR}..."
PDF_FILES=()
while IFS= read -r -d '' f; do
    PDF_FILES+=("$f")
done < <(find "$INPUT_DIR" -maxdepth 1 -name "*.pdf" -print0 2>/dev/null)

if [[ ${#PDF_FILES[@]} -eq 0 ]]; then
    err "No hay PDFs en ${INPUT_DIR}. Agrega documentos y vuelve a ejecutar."
fi
info "${#PDF_FILES[@]} documento(s) encontrado(s):"
for f in "${PDF_FILES[@]}"; do echo "    - $(basename "$f")"; done

# ── 5. Crear directorios necesarios ──────────────────────────────────────────
mkdir -p volumes/db volumes/output volumes/originals volumes/redis \
         volumes/models/ollama volumes/models/huggingface \
         volumes/models/marker volumes/models/mineru volumes/models/torch

# ── 6. Levantar servicios ────────────────────────────────────────────────────
step "Iniciando servicios (redis, ollama, backend, worker, summarizer)..."
docker compose up -d --remove-orphans --force-recreate
info "Servicios lanzados"

# ── 7. Esperar que el backend responda ───────────────────────────────────────
step "Esperando que el backend esté listo..."
MAX_WAIT=120; ELAPSED=0
echo -n "  "
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    [[ $ELAPSED -ge $MAX_WAIT ]] && { echo ""; err "Backend sin respuesta en ${MAX_WAIT}s — revisa: ./logs.sh"; }
    echo -n "."; sleep 3; ELAPSED=$((ELAPSED + 3))
done
echo ""; info "Backend listo (${ELAPSED}s)"

# ── 8. Encolar todos los PDFs ────────────────────────────────────────────────
step "Encolando documentos para procesamiento OCR..."
QUEUED=0; FAILED=0
for pdf in "${PDF_FILES[@]}"; do
    name=$(basename "$pdf")
    response=$(curl -s -w "\n%{http_code}" -X POST http://localhost:8000/api/jobs/upload \
        -F "file=@${pdf}" 2>&1)
    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | head -1)
    if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
        job_id=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','?')[:8])" 2>/dev/null || echo "?")
        echo -e "  ${GREEN}→${NC} ${name}  [job: ${job_id}...]"
        QUEUED=$((QUEUED + 1))
    else
        echo -e "  ${RED}✗${NC} ${name}  [HTTP ${http_code}]"
        FAILED=$((FAILED + 1))
    fi
done
echo ""; info "$QUEUED documento(s) encolado(s)"
[[ $FAILED -gt 0 ]] && warn "$FAILED documento(s) fallaron al encolar"

# ── 9. Resumen ────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║       Sistema OCR iniciado correctamente         ║${NC}"
echo -e "${GREEN}  ╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}  ║  API:     http://localhost:8000/docs             ║${NC}"
echo -e "${GREEN}  ║  Ollama:  http://localhost:11434                 ║${NC}"
echo -e "${GREEN}  ╠══════════════════════════════════════════════════╣${NC}"
printf   "${GREEN}  ║  Input:   %-38s ║${NC}\n" "${INPUT_DIR}"
printf   "${GREEN}  ║  Output:  %-38s ║${NC}\n" "${OUTPUT_DIR}"
echo -e "${GREEN}  ╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}  ║  Ver logs:      ./logs.sh                        ║${NC}"
echo -e "${GREEN}  ║  Ver progreso:  ./status.sh                      ║${NC}"
echo -e "${GREEN}  ║  Reanudar:      ./resume.sh                      ║${NC}"
echo -e "${GREEN}  ║  Detener:       docker compose down              ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════╝${NC}"
echo ""
