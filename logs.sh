#!/usr/bin/env bash
# =============================================================================
# logs.sh — Ver logs del sistema OCR en tiempo real
#
# Uso:
#   ./logs.sh              # logs del worker (OCR) — default
#   ./logs.sh backend      # logs del backend (API)
#   ./logs.sh all          # todos los servicios
#   ./logs.sh worker -n 100  # últimas 100 líneas
# =============================================================================
cd "$(dirname "${BASH_SOURCE[0]}")"

TARGET="${1:-worker}"
shift 2>/dev/null || true
EXTRA_ARGS=("$@")

case "$TARGET" in
    all)
        echo "→ Logs de todos los servicios (Ctrl+C para salir)"
        docker compose logs -f --tail=50 "${EXTRA_ARGS[@]}"
        ;;
    backend)
        echo "→ Logs del backend API (Ctrl+C para salir)"
        docker compose logs -f --tail=50 backend "${EXTRA_ARGS[@]}"
        ;;
    worker)
        echo "→ Logs del worker OCR (Ctrl+C para salir)"
        docker compose logs -f --tail=50 worker "${EXTRA_ARGS[@]}"
        ;;
    *)
        echo "→ Logs de '$TARGET' (Ctrl+C para salir)"
        docker compose logs -f --tail=50 "$TARGET" "${EXTRA_ARGS[@]}"
        ;;
esac
