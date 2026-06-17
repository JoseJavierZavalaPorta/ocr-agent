#!/usr/bin/env bash
# =============================================================================
# status.sh — Estado de todos los jobs OCR
#
# Uso:
#   ./status.sh           # resumen de todos los jobs
#   ./status.sh <job_id>  # detalle de un job específico
# =============================================================================
cd "$(dirname "${BASH_SOURCE[0]}")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'

API="http://localhost:8000"

# Verificar que el backend está corriendo
if ! curl -sf "$API/health" > /dev/null 2>&1; then
    echo -e "${RED}✗${NC} El backend no está disponible. Ejecuta ./start.sh primero."
    exit 1
fi

JOB_ID="${1:-}"

if [ -n "$JOB_ID" ]; then
    # Detalle de un job específico
    curl -s "$API/api/jobs/$JOB_ID" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"Job: {d['id']}\")
print(f\"Archivo: {d.get('filename','?')}\")
print(f\"Estado: {d.get('status','?')}\")
print(f\"Páginas: {d.get('processed_pages','?')}/{d.get('total_pages','?')}\")
conf = d.get('avg_confidence') or 0
print(f\"Confianza prom: {conf:.0%}\")
print()
pages = d.get('pages', [])
if pages:
    print('  Pág | Estado       | Motor   | Conf  | Detalle')
    print('  ----+--------------+---------+-------+' + '-'*40)
    for p in pages:
        status = p.get('status','?')
        engine = (p.get('ocr_engine') or '?')[:8]
        conf = p.get('confidence_score') or p.get('confidence') or 0
        err = (p.get('error_message') or '')[:50]
        icon = '✓' if status == 'COMPLETED' else ('⚠' if status == 'ERROR' else '…')
        print(f\"  {p['page_number']+1:3d} | {icon} {status:10s} | {engine:7s} | {conf:5.0%} | {err}\")
"
else
    # Resumen de todos los jobs
    curl -s "$API/api/jobs" | python3 -c "
import sys, json

jobs = json.load(sys.stdin)
if not jobs:
    print('  No hay jobs registrados.')
    sys.exit(0)

print()
print(f\"  {'Archivo':<32} {'Estado':<12} {'Páginas':<10} {'Conf':<7} Job ID\")
print('  ' + '-'*80)

STATUS_ICON = {
    'COMPLETED': '\033[0;32m✓\033[0m',
    'PARTIAL':   '\033[1;33m⚠\033[0m',
    'ERROR':     '\033[0;31m✗\033[0m',
    'PROCESSING':'\033[0;34m…\033[0m',
    'PENDING':   '\033[0;34m◌\033[0m',
}
for j in jobs:
    status = j.get('status','?')
    icon = STATUS_ICON.get(status, ' ')
    pages = f\"{j.get('processed_pages','?')}/{j.get('total_pages','?')}\"
    conf = j.get('avg_confidence') or 0
    job_id = j.get('id','?')[:8]
    fname = j.get('filename','?')[:31]
    print(f\"  {fname:<32} {icon} {status:<10} {pages:<10} {conf:5.0%}  {job_id}...\")

total = len(jobs)
done  = sum(1 for j in jobs if j.get('status') == 'COMPLETED')
part  = sum(1 for j in jobs if j.get('status') == 'PARTIAL')
proc  = sum(1 for j in jobs if j.get('status') in ('PROCESSING','PENDING','OCR'))
print()
print(f\"  Total: {total}  |  Completados: {done}  |  Parciales: {part}  |  En proceso: {proc}\")
print()
"
fi
