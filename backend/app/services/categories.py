"""
Carga y valida categorias.json — lo deja el equipo de negocio en la misma
carpeta de entrada (settings.input_path), junto a los PDFs originales.

Formato esperado:
{
  "categorias": [
    {"nombre": "Actas", "descripcion": "..."},
    {"nombre": "Correspondencia", "descripcion": "..."}
  ]
}
"""

import json
from pathlib import Path

from app.config import get_settings

settings = get_settings()

CATEGORIES_FILENAME = "categorias.json"


class CategoriesConfigError(Exception):
    """categorias.json falta, no es JSON válido, o no respeta el esquema esperado."""


def categories_file_path() -> Path:
    return Path(settings.input_path) / CATEGORIES_FILENAME


def load_categories() -> list[dict]:
    """
    Retorna [{"nombre": str, "descripcion": str}, ...].
    Levanta CategoriesConfigError con mensaje claro si algo no calza —
    quien la llame debe capturarla y NO dejar que tumbe el worker.
    """
    path = categories_file_path()

    if not path.exists():
        raise CategoriesConfigError(
            f"No se encontró {CATEGORIES_FILENAME} en {settings.input_path}. "
            f"Debe colocarse en la misma carpeta que los PDFs de entrada."
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CategoriesConfigError(f"No se pudo leer {path}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CategoriesConfigError(
            f"{CATEGORIES_FILENAME} no es JSON válido (línea {e.lineno}, col {e.colno}): {e.msg}"
        ) from e

    if not isinstance(data, dict) or "categorias" not in data:
        raise CategoriesConfigError(
            f"{CATEGORIES_FILENAME} debe tener la forma "
            '{"categorias": [{"nombre": "...", "descripcion": "..."}]} — '
            f"no se encontró la clave 'categorias'."
        )

    items = data["categorias"]
    if not isinstance(items, list) or not items:
        raise CategoriesConfigError(
            f"'categorias' en {CATEGORIES_FILENAME} debe ser una lista no vacía."
        )

    categorias: list[dict] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or "nombre" not in item or "descripcion" not in item:
            raise CategoriesConfigError(
                f"categorias[{i}] en {CATEGORIES_FILENAME} debe tener 'nombre' y 'descripcion'. "
                f"Recibido: {item!r}"
            )
        nombre = str(item["nombre"]).strip()
        descripcion = str(item["descripcion"]).strip()
        if not nombre:
            raise CategoriesConfigError(f"categorias[{i}] tiene 'nombre' vacío en {CATEGORIES_FILENAME}.")
        categorias.append({"nombre": nombre, "descripcion": descripcion})

    return categorias
