"""Infraestrutura do catálogo SQLite e conversões sem ponto flutuante."""

from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "catalog.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY CHECK (category_id > 0),
    name TEXT NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY CHECK (product_id > 0),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    description TEXT NOT NULL,
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'discontinued', 'coming_soon')),
    specs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotions (
    promotion_id INTEGER PRIMARY KEY CHECK (promotion_id > 0),
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    discount_percent INTEGER NOT NULL CHECK (discount_percent BETWEEN 0 AND 100),
    description TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_promotion_per_product
    ON promotions(product_id) WHERE is_active = 1;
"""


class CatalogError(RuntimeError):
    """O catálogo não está pronto para consulta."""


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def brl_to_cents(value: str | Decimal) -> int:
    """Converta reais em centavos, rejeitando frações de centavo e floats."""
    if not isinstance(value, (str, Decimal)):
        raise ValueError("Informe o valor em reais como texto ou Decimal, usando ponto decimal.")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0:
            raise ValueError("O valor deve ser finito e não negativo.")
        if amount > Decimal(2**63 - 1).scaleb(-2):
            raise ValueError("O valor deve caber no SQLite.")
        rounded = amount.quantize(Decimal("0.01"))
        if amount != rounded:
            raise ValueError("O valor deve caber no SQLite e ter no máximo duas casas decimais.")
        return int(rounded * 100)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Valor monetário inválido; use ponto decimal, como 599.90.") from exc


def connect_database(path: Path, *, read_only: bool = True) -> sqlite3.Connection:
    path = Path(path).resolve()
    if read_only and not path.is_file():
        raise CatalogError("Catálogo não encontrado. Execute 'python -m emporio.import_data'.")
    target = path.as_uri() + "?mode=ro" if read_only else str(path)
    connection = sqlite3.connect(target, uri=read_only)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.create_function("normalize_text", 1, normalize_text, deterministic=True)
    return connection
