"""Consultas parametrizadas e regras de preço do catálogo, independentes do LLM."""

from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from emporio.database import DEFAULT_DATABASE, brl_to_cents, connect_database, normalize_text


@dataclass(frozen=True)
class Category:
    category_id: int
    name: str
    description: str


@dataclass(frozen=True)
class Product:
    product_id: int
    name: str
    category_id: int
    category_name: str
    description: str
    stock_quantity: int
    status: str
    specs: dict[str, Any]
    created_at: str
    price_cents: int
    effective_price_cents: int
    promotion_id: int | None
    discount_percent: int
    promotion_description: str | None

    @property
    def available(self) -> bool:
        return self.status == "active" and self.stock_quantity > 0

    @property
    def price_brl(self) -> Decimal:
        return Decimal(self.price_cents).scaleb(-2)

    @property
    def effective_price_brl(self) -> Decimal:
        return Decimal(self.effective_price_cents).scaleb(-2)


PRODUCT_QUERY = """
SELECT p.*, c.name AS category_name,
       pr.promotion_id, pr.discount_percent, pr.description AS promotion_description
FROM products p
JOIN categories c ON c.category_id = p.category_id
LEFT JOIN promotions pr ON pr.product_id = p.product_id AND pr.is_active = 1
"""


def _product_from_row(row) -> Product:
    percent = row["discount_percent"] or 0
    # Arredondamento half-up para centavos, usando apenas aritmética inteira.
    effective = (row["price_cents"] * (100 - percent) + 50) // 100
    return Product(
        product_id=row["product_id"], name=row["name"], category_id=row["category_id"],
        category_name=row["category_name"], description=row["description"],
        stock_quantity=row["stock_quantity"], status=row["status"],
        specs=json.loads(row["specs_json"]), created_at=row["created_at"],
        price_cents=row["price_cents"], effective_price_cents=effective,
        promotion_id=row["promotion_id"], discount_percent=percent,
        promotion_description=row["promotion_description"],
    )


def _positive_integer(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} deve ser um inteiro positivo.")


class Catalog:
    def __init__(self, database: Path = DEFAULT_DATABASE):
        self.database = Path(database)

    def list_categories(self) -> list[Category]:
        with closing(connect_database(self.database)) as connection:
            rows = connection.execute("SELECT * FROM categories ORDER BY category_id").fetchall()
        return [Category(**dict(row)) for row in rows]

    def get_product(self, product_id: int) -> Product | None:
        """Inclui indisponíveis, para permitir explicar seu status ao cliente."""
        _positive_integer(product_id, "product_id")
        with closing(connect_database(self.database)) as connection:
            row = connection.execute(PRODUCT_QUERY + " WHERE p.product_id = ?", (product_id,)).fetchone()
        return _product_from_row(row) if row else None

    def search_products(
        self, query: str = "", *, category_id: int | None = None,
        max_price_brl: str | Decimal | None = None, available_only: bool = True, limit: int = 10,
    ) -> list[Product]:
        """Combine filtros; orçamento e ordenação usam o preço após promoção ativa."""
        _positive_integer(limit, "limit")
        if category_id is not None:
            _positive_integer(category_id, "category_id")
        if not isinstance(query, str) or type(available_only) is not bool:
            raise ValueError("query deve ser texto e available_only deve ser booleano.")
        max_cents = brl_to_cents(max_price_brl) if max_price_brl is not None else None
        conditions, parameters = [], []
        if available_only:
            conditions.append("p.status = 'active' AND p.stock_quantity > 0")
        if category_id is not None:
            conditions.append("p.category_id = ?")
            parameters.append(category_id)
        for token in normalize_text(query).split():
            conditions.append("instr(normalize_text(p.name || ' ' || p.description || ' ' || c.name), ?) > 0")
            parameters.append(token)
        sql = PRODUCT_QUERY + (" WHERE " + " AND ".join(conditions) if conditions else "")
        with closing(connect_database(self.database)) as connection:
            products = [_product_from_row(row) for row in connection.execute(sql, parameters)]
        # O snapshot é pequeno: calcular em Python evita coerção monetária para REAL no SQLite.
        if max_cents is not None:
            products = [product for product in products if product.effective_price_cents <= max_cents]
        return sorted(products, key=lambda p: (p.effective_price_cents, p.product_id))[:limit]
