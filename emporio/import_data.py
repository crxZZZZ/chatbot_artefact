"""Importação transacional dos CSVs de catálogo fornecidos no desafio."""

import argparse
from contextlib import closing
import csv
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
from typing import Callable

from emporio.database import DEFAULT_DATABASE, DEFAULT_SOURCE_DIR, SCHEMA, brl_to_cents, connect_database


class DataImportError(ValueError):
    """Fonte inválida: a importação não deve substituir o catálogo anterior."""


def _text(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None or not value.strip():
        raise ValueError(f"Campo obrigatório vazio: {key}.")
    return value.strip()


def _integer(row: dict, key: str, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    text = _text(row, key)
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"{key} deve ser inteiro.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} fora do intervalo permitido: {minimum} a {maximum}.")
    return value


def _category(row: dict) -> tuple:
    return _integer(row, "category_id", 1), _text(row, "name"), _text(row, "description")


def _product(row: dict) -> tuple:
    status = _text(row, "status")
    if status not in {"active", "discontinued", "coming_soon"}:
        raise ValueError(f"Status desconhecido: {status}.")
    specs = json.loads(_text(row, "specs"), parse_constant=_reject_json_constant)
    if not isinstance(specs, dict):
        raise ValueError("specs deve conter um objeto JSON.")
    created_at = _text(row, "created_at")
    date.fromisoformat(created_at)
    return (
        _integer(row, "product_id", 1), brl_to_cents(_text(row, "price_brl")),
        _text(row, "name"), _integer(row, "category_id", 1), _text(row, "description"),
        _integer(row, "stock_quantity"), status,
        json.dumps(specs, ensure_ascii=False, allow_nan=False), created_at,
    )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Constante JSON inválida: {value}.")


def _promotion(row: dict) -> tuple:
    return (
        _integer(row, "promotion_id", 1), _integer(row, "product_id", 1),
        _integer(row, "discount_percent", 0, 100), _text(row, "description"),
        _integer(row, "is_active", 0, 1),
    )


SOURCES = {
    "categories": (("category_id", "name", "description"), _category),
    "products": (("product_id", "price_brl", "name", "category_id", "description",
                  "stock_quantity", "status", "specs", "created_at"), _product),
    "promotions": (("promotion_id", "product_id", "discount_percent", "description", "is_active"), _promotion),
}


def _read_csv(path: Path, columns: tuple[str, ...], parse: Callable) -> list[tuple[int, tuple]]:
    rows = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)) or not set(columns).issubset(headers):
                raise DataImportError(f"{path.name}: cabeçalho inválido; campos esperados: {', '.join(columns)}.")
            for row in reader:
                try:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("Quantidade de campos incompatível com o cabeçalho.")
                    rows.append((reader.line_num, parse(row)))
                except (ValueError, OverflowError) as exc:
                    raise DataImportError(f"{path.name}, linha {reader.line_num}: {exc}") from exc
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DataImportError(f"Não foi possível ler {path}: {exc}") from exc
    return rows


def import_catalog(source_dir: Path = DEFAULT_SOURCE_DIR, database: Path = DEFAULT_DATABASE) -> dict[str, int]:
    """Recarregue o snapshot completo; falhas preservam os registros anteriores."""
    source_dir, database = Path(source_dir), Path(database)
    parsed = {
        table: _read_csv(source_dir / f"{table}.csv", columns, parser)
        for table, (columns, parser) in SOURCES.items()
    }
    if not parsed["categories"] or not parsed["products"]:
        raise DataImportError("O catálogo precisa conter categorias e produtos.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_database(database, read_only=False)) as connection:
        connection.executescript(SCHEMA)
        with connection:
            for table in ("promotions", "products", "categories"):
                connection.execute(f"DELETE FROM {table}")
            for table, rows in parsed.items():
                placeholders = ", ".join("?" for _ in SOURCES[table][0])
                for line, values in rows:
                    try:
                        connection.execute(f"INSERT INTO {table} VALUES ({placeholders})", values)
                    except sqlite3.IntegrityError as exc:
                        raise DataImportError(f"{table}.csv, linha {line}: {exc}") from exc
    return {table: len(rows) for table, rows in parsed.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Importe categorias, produtos e promoções para SQLite.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    args = parser.parse_args()
    try:
        counts = import_catalog(args.source_dir, args.database)
    except (DataImportError, OSError, sqlite3.Error) as exc:
        print(f"Erro ao importar catálogo: {exc}", file=sys.stderr)
        return 1
    print(f"Catálogo importado em {args.database.resolve()}")
    print(
        f"{counts['categories']} categorias, {counts['products']} produtos, "
        f"{counts['promotions']} promoções."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
