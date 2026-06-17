#!/usr/bin/env bash
# =============================================================================
# resume.sh — OCR Agent
# Reinicia los servicios y reanuda jobs interrumpidos por apagado/reinicio.
# Los jobs reanudan desde la última página completada (checkpointing).
#
# Uso:
#   ./resume.sh                          # reanuda con input por defecto
#   ./resume.sh /ruta/a/mis/documentos   # reanuda con la ruta indicada
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

# ── Directorio de input (argumento opcional) ──────────────────────────────────
INPUT_ARG="${1:-}"
if [[ -n "$INPUT_ARG" ]]; then
    INPUT_DIR="$(realpath "$INPUT_ARG")"
    [[ -d "$INPUT_DIR" ]] || err "El directorio no existe: $INPUT_DIR"
else
    INPUT_DIR="$(realpath ./volumes/input)"
fi
export INPUT_DIR

echo -e "${CYAN}"
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║       OCR Agent — Reanudación de Jobs         ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Input: ${CYAN}${INPUT_DIR}${NC}"

# ── 1. Verificar .env ─────────────────────────────────────────────────────────
[[ -f .env ]] || { cp .env.example .env; warn ".env creado desde .env.example — revisa la configuración"; }

# ── 2. Verificar que hay BD existente ────────────────────────────────────────
if [[ ! -f volumes/db/ocr.db ]]; then
    warn "No hay base de datos — no hay jobs para reanudar"
    warn "Usa ./start.sh para iniciar desde cero"
    exit 0
fi

# ── 3. Reiniciar servicios (sin limpiar BD) ───────────────────────────────────
step "Reiniciando servicios..."
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --remove-orphans --force-recreate
info "Servicios reiniciados"

# ── 4. Esperar que el backend responda ───────────────────────────────────────
step "Esperando que el backend esté listo..."
MAX_WAIT=120; ELAPSED=0
echo -n "  "
until curl -sf http://localhost:8000/health > /dev/null 2>&1; do
    [[ $ELAPSED -ge $MAX_WAIT ]] && { echo ""; err "Backend sin respuesta en ${MAX_WAIT}s — revisa: ./logs.sh"; }
    echo -n "."; sleep 3; ELAPSED=$((ELAPSED + 3))
done
echo ""; info "Backend listo (${ELAPSED}s)"

# ── 5. Re-encolar jobs interrumpidos ─────────────────────────────────────────
step "Buscando jobs interrumpidos para reanudar..."
RESPONSE=$(curl -s -X POST http://localhost:8000/api/jobs/resume 2>&1)
RESUMED=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('resumed', 0))" 2>/dev/null || echo "0")

if [[ "$RESUMED" -gt 0 ]]; then
    info "$RESUMED job(s) reanudado(s) desde el último checkpoint"
    echo "$RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for jid in d.get('job_ids', []):
    print(f'    → Job {jid[:8]}...')
" 2>/dev/null || true
else
    info "No hay jobs interrumpidos — todos los jobs están en estado final"
fi

# ── 6. Estado actual de jobs ──────────────────────────────────────────────────
step "Estado actual de todos los jobs:"
curl -s http://localhost:8000/api/jobs | python3 -c "
import sys, json
jobs = json.load(sys.stdin)
if not jobs:
    print('  (sin jobs en la base de datos)')
else:
    for j in sorted(jobs, key=lambda x: x.get('filename', '')):
        st = j.get('status', '?')
        conf = round(j.get('avg_confidence', 0) * 100)
        pp = j.get('processed_pages', 0)
        tp = j.get('total_pages', 0) or '?'
        fn = j.get('filename', '?')[:35]
        icon = '✅' if st == 'completed' else ('❌' if st == 'error' else '🔄' if st in ('ocr', 'correcting', 'validating', 'preprocessing') else '⏳')
        print(f'  {icon} {fn:<35} {st:<12} {pp}/{tp}  {conf}%')
" 2>/dev/null || warn "No se pudo obtener el estado de los jobs"

echo ""
echo -e "${GREEN}  ╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║  Reanudación completada                          ║${NC}"
echo -e "${GREEN}  ╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}  ║  Ver progreso:  ./status.sh                      ║${NC}"
echo -e "${GREEN}  ║  Ver logs:      ./logs.sh                        ║${NC}"
echo -e "${GREEN}  ║  Output:        ./volumes/output/                ║${NC}"
echo -e "${GREEN}  ╚══════════════════════════════════════════════════╝${NC}"
echo ""
