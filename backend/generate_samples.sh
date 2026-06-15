#!/usr/bin/env bash
# =============================================================================
# generate_samples.sh
# Genera 3 PDFs de muestra en /data/input/ para demostrar el pipeline OCR.
# Ejecutar dentro del container worker:
#   docker compose exec worker bash /app/generate_samples.sh
# =============================================================================

set -euo pipefail

INPUT_PATH="${INPUT_PATH:-/data/input}"
GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $*"; }

info "Generando documentos de muestra en ${INPUT_PATH}..."

python3 - <<PYEOF
import fitz
import os

out = os.environ.get("INPUT_PATH", "/data/input")
os.makedirs(out, exist_ok=True)

# ── 1. Acta de sesión municipal (1942) — texto impreso histórico ──────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(
    fitz.Rect(50, 50, 545, 792),
    """ACTA DE SESIÓN ORDINARIA

Ciudad de Lima, a los veinte días del mes de marzo del año mil novecientos
cuarenta y dos, reunidos en la sala de sesiones del Honorable Ayuntamiento,
bajo la presidencia del señor Alcalde Don Roberto Fernández Castillo, con
asistencia de los señores regidores que suscriben al margen.

Se dio lectura al acta de la sesión anterior, la cual fue aprobada por
unanimidad sin observación alguna.

El señor Presidente manifestó que el objeto de la reunión era tratar los
siguientes asuntos de interés municipal:

PRIMERO.- Aprobación del presupuesto para la construcción del nuevo mercado
municipal, cuyo costo asciende a la suma de diez mil soles oro.

SEGUNDO.- Nombramiento de una comisión encargada de inspeccionar las obras
públicas en ejecución en la avenida principal de la ciudad.

TERCERO.- Informe sobre el estado de las escuelas municipales y las
necesidades de material educativo para el presente año escolar 1942-1943.

No habiendo más asuntos que tratar, se levantó la sesión siendo las
diecisiete horas del mismo día.

                El Secretario,                    El Alcalde,
           Manuel García López           Roberto Fernández Castillo""",
    fontsize=11,
    fontname="helv",
)
doc.save(f"{out}/muestra_acta_1942.pdf")
doc.close()
print(f"  ✓ muestra_acta_1942.pdf  (acta municipal, texto impreso)")

# ── 2. Padrón de vecinos (1955) — documento con tabla ────────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(
    fitz.Rect(40, 50, 555, 792),
    """PADRÓN DE VECINOS — MUNICIPIO DE SAN MARTÍN DE PORRES
Año: 1955

+-------------------+-------+------------------+-------------------+
| NOMBRE Y APELLIDO | EDAD  | PROFESION        | OBSERVACIONES     |
+-------------------+-------+------------------+-------------------+
| Garcia, Juan R.   |  34   | Comerciante      | Propietario       |
| Rodriguez, Maria  |  28   | Maestra          | Inquilina         |
| Lopez, Carlos A.  |  45   | Agricultor       | Propietario       |
| Sanchez, Rosa P.  |  52   | Lavandera        | Inquilina         |
| Flores, Pedro M.  |  31   | Carpintero       | Propietario       |
| Torres, Ana L.    |  23   | Sin profesion    | Inquilina         |
| Vargas, Luis F.   |  67   | Jubilado         | Propietario       |
| Mendoza, Elena G. |  41   | Modista          | Inquilina         |
+-------------------+-------+------------------+-------------------+

Total de vecinos registrados: 8
Total propietarios: 4   Total inquilinos: 4

Fecha de elaboración: 15 de enero de 1955
Responsable del empadronamiento: Agente Municipal Nro. 7
Firma del Empadronador: _______________________""",
    fontsize=10,
    fontname="cour",
)
doc.save(f"{out}/muestra_padron_1955.pdf")
doc.close()
print(f"  ✓ muestra_padron_1955.pdf  (padrón con tabla, texto tabulado)")

# ── 3. Carta personal (1923) — correspondencia histórica ─────────────────────
doc = fitz.open()
page = doc.new_page(width=595, height=842)
page.insert_textbox(
    fitz.Rect(60, 60, 535, 782),
    """                                     Arequipa, 3 de julio de 1923

Estimado hermano:

Recibo tu apreciada carta del mes pasado con mucho júbilo, pues hacía
tiempo que no tenía noticias tuyas. Me alegra saber que tu familia goza
de buena salud y que los negocios van viento en popa en esa ciudad.

Por acá las cosas siguen su curso habitual. La hacienda ha dado buena
cosecha este año gracias a las lluvias que cayeron en abundancia durante
los meses de febrero y marzo. El precio de la lana ha subido
considerablemente en el mercado de Mollendo, lo que nos permitirá saldar
las deudas pendientes con el comerciante don Aurelio Quispe.

Los muchachos están creciendo bien. El mayor, Ernestito, ya tiene doce
años cumplidos y ayuda con gran ánimo en las faenas del campo. La pequeña
Merceditas empezará la escuela en septiembre próximo; ya sabe leer algunas
palabras y es muy aplicada según dice su madre.

Esperamos que la temporada de lluvias no sea tan intensa como el año
pasado, que nos ocasionó serios daños en los sembríos del lado norte.

Sin más por el momento, esperando verte pronto en tu próxima visita,
te envía un fuerte abrazo tu hermano que te quiere,

                                        Eduardo Málaga Cornejo
                                        Hacienda Santa Rosa, Arequipa""",
    fontsize=12,
    fontname="helv",
)
doc.save(f"{out}/muestra_carta_1923.pdf")
doc.close()
print(f"  ✓ muestra_carta_1923.pdf  (carta personal, estilo manuscrito)")

print()
print("Listos. El file watcher los detectará en segundos.")
print("Abre el dashboard para ver el procesamiento en tiempo real.")
PYEOF
