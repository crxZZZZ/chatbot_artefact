"""Regras do catálogo com fontes reais e variações isoladas em diretórios temporários."""

from contextlib import closing
import csv
from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from emporio.catalog import Catalog
from emporio.database import CatalogError, DEFAULT_SOURCE_DIR, brl_to_cents, connect_database
from emporio.import_data import DataImportError, import_catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "raw"
        shutil.copytree(DEFAULT_SOURCE_DIR, self.source)
        self.database = self.root / "catalog.sqlite3"
        self.counts = import_catalog(self.source, self.database)
        self.catalog = Catalog(self.database)

    def read_rows(self, table):
        with (self.source / f"{table}.csv").open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            return reader.fieldnames, list(reader)

    def write_rows(self, table, fields, rows):
        with (self.source / f"{table}.csv").open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def update_product(self, product_id, **changes):
        fields, rows = self.read_rows("products")
        next(row for row in rows if row["product_id"] == str(product_id)).update(changes)
        self.write_rows("products", fields, rows)

    def add_promotion(self, *, product_id="81", discount_percent="10"):
        fields, rows = self.read_rows("promotions")
        rows.append({"promotion_id": "999", "product_id": product_id,
                     "discount_percent": discount_percent, "description": "Oferta de teste", "is_active": "1"})
        self.write_rows("promotions", fields, rows)

    def test_imports_original_counts_and_valid_foreign_keys(self):
        self.assertEqual(self.counts, {"categories": 9, "products": 65, "promotions": 25})
        with closing(connect_database(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT count(*) FROM promotions WHERE is_active = 1").fetchone()[0], 4)
        self.assertEqual(len(self.catalog.list_categories()), 9)
        product = self.catalog.get_product(81)
        self.assertEqual(product.price_cents, 59990)
        self.assertEqual(product.specs["strings"], "nylon")

    def test_reimport_replaces_snapshot_without_duplicates_or_stale_products(self):
        fields, rows = self.read_rows("products")
        self.write_rows("products", fields, [row for row in rows if row["product_id"] != "81"])
        for _ in range(2):
            counts = import_catalog(self.source, self.database)
            self.assertEqual(counts["products"], 64)
            self.assertIsNone(self.catalog.get_product(81))
            self.assertEqual(self.catalog.get_product(82).name, "Yamaha C70 Nylon Natural")

    def test_only_active_products_with_positive_stock_are_available(self):
        for product_id in (96, 113, 130, 136):
            with self.subTest(product_id=product_id):
                product = self.catalog.get_product(product_id)
                self.assertFalse(product.available)
                self.assertEqual(self.catalog.search_products(product.name), [])
                self.assertEqual(
                    self.catalog.search_products(product.name, available_only=False)[0].product_id,
                    product_id,
                )
        self.assertEqual(self.catalog.get_product(136).stock_quantity, 13)
        self.assertTrue(self.catalog.get_product(81).available)

    def test_active_promotions_have_expected_prices(self):
        expected = {90: (18, 196718), 94: (8, 551908), 121: (20, 43920), 127: (10, 32310)}
        for product_id, (percent, cents) in expected.items():
            with self.subTest(product_id=product_id):
                product = self.catalog.get_product(product_id)
                self.assertEqual(product.discount_percent, percent)
                self.assertEqual(product.effective_price_cents, cents)
                self.assertIsNotNone(product.promotion_id)
                self.assertIsNotNone(product.promotion_description)

    def test_inactive_promotions_are_not_applied_or_accumulated(self):
        product = self.catalog.get_product(99)  # Duas promoções inativas na fonte.
        self.assertIsNone(product.promotion_id)
        self.assertEqual(product.discount_percent, 0)
        self.assertEqual(product.effective_price_brl, Decimal("1199.00"))
        self.assertEqual(product.price_brl, product.effective_price_brl)

    def test_budget_includes_discount_and_is_inclusive_at_cent_boundary(self):
        found = self.catalog.search_products("Ohana CK-20", max_price_brl="439.20")
        self.assertEqual([p.product_id for p in found], [121])
        self.assertEqual(self.catalog.search_products("Ohana CK-20", max_price_brl="439.19"), [])

    def test_rounds_half_cent_up_instead_of_truncating_or_rounding_to_even(self):
        self.update_product(81, price_brl="10.05")
        self.add_promotion()
        import_catalog(self.source, self.database)
        product = self.catalog.get_product(81)
        self.assertEqual(product.effective_price_cents, 905)
        self.assertEqual(product.effective_price_brl, Decimal("9.05"))

    def test_zero_and_full_discount_boundaries(self):
        self.update_product(81, price_brl="10.05")
        self.add_promotion(discount_percent="0")
        import_catalog(self.source, self.database)
        self.assertEqual(self.catalog.get_product(81).effective_price_cents, 1005)
        fields, rows = self.read_rows("promotions")
        rows[-1]["discount_percent"] = "100"
        self.write_rows("promotions", fields, rows)
        import_catalog(self.source, self.database)
        self.assertEqual(self.catalog.get_product(81).effective_price_cents, 0)
        self.assertEqual([p.product_id for p in self.catalog.search_products("Yamaha C40", max_price_brl="0")], [81])

    def test_search_combines_tokens_accents_case_and_category(self):
        found = self.catalog.search_products("VIOLAO YAMAHA C40", category_id=5, max_price_brl="1000")
        self.assertEqual([p.product_id for p in found], [81])
        self.assertEqual(self.catalog.search_products("Yamaha C40", category_id=9), [])

    def test_price_order_has_stable_id_tiebreaker_and_limit(self):
        self.update_product(81, name="Empate teste", price_brl="500")
        self.update_product(82, name="Empate teste", price_brl="500")
        self.update_product(83, name="Empate teste", price_brl="400")
        import_catalog(self.source, self.database)
        self.assertEqual([p.product_id for p in self.catalog.search_products("Empate teste", limit=2)], [83, 81])

    def test_user_query_is_literal_not_sql(self):
        self.assertEqual(self.catalog.search_products("%' OR 1=1; DROP TABLE products; --"), [])
        self.assertEqual(self.catalog.get_product(81).product_id, 81)
        # '%' é literal: apenas a descrição "100% Birch" corresponde à busca.
        self.assertEqual([p.product_id for p in self.catalog.search_products("%")], [140])

    def test_missing_product_and_no_matches(self):
        self.assertIsNone(self.catalog.get_product(999999))
        self.assertEqual(self.catalog.search_products("instrumento-inexistente-xyz"), [])

    def test_invalid_query_parameters(self):
        for kwargs in ({"limit": 0}, {"limit": True}, {"category_id": -1}, {"max_price_brl": "-1"},
                       {"max_price_brl": "NaN"}, {"available_only": "false"}, {"query": None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.catalog.search_products(**kwargs)

    def test_foreign_key_failure_rolls_back_all_replacements(self):
        self.update_product(81, price_brl="1.00")
        self.update_product(82, category_id="9999")
        with self.assertRaisesRegex(DataImportError, "products.csv.*FOREIGN KEY"):
            import_catalog(self.source, self.database)
        self.assertEqual(self.catalog.get_product(81).price_cents, 59990)
        self.assertEqual(len(self.catalog.list_categories()), 9)
        self.assertEqual(self.catalog.get_product(121).effective_price_cents, 43920)

    def test_duplicate_product_id_rolls_back(self):
        fields, rows = self.read_rows("products")
        self.write_rows("products", fields, [*rows, rows[0]])
        with self.assertRaisesRegex(DataImportError, "products.csv.*UNIQUE"):
            import_catalog(self.source, self.database)
        self.assertEqual(self.catalog.get_product(81).price_cents, 59990)

    def test_conflicting_active_promotions_fail_instead_of_choosing_silently(self):
        self.add_promotion(product_id="127")
        with self.assertRaisesRegex(DataImportError, "promotions.csv.*UNIQUE"):
            import_catalog(self.source, self.database)
        self.assertEqual(self.catalog.get_product(127).discount_percent, 10)

    def test_invalid_product_values_report_source_and_preserve_snapshot(self):
        for changes in ({"price_brl": "10.001"}, {"specs": "[]"}, {"specs": '{"bad": NaN}'},
                        {"stock_quantity": "-1"}, {"status": "unknown"}, {"created_at": "2026-02-30"}):
            with self.subTest(changes=changes):
                # Cada variação parte da mesma fonte, sem acumular erros anteriores.
                shutil.copyfile(DEFAULT_SOURCE_DIR / "products.csv", self.source / "products.csv")
                self.update_product(81, **changes)
                with self.assertRaisesRegex(DataImportError, "products.csv, linha"):
                    import_catalog(self.source, self.database)
                self.assertEqual(self.catalog.get_product(81).price_cents, 59990)

    def test_invalid_promotion_values_fail(self):
        for key, value in (("discount_percent", "101"), ("discount_percent", "-1"), ("is_active", "true")):
            with self.subTest(key=key, value=value):
                shutil.copyfile(DEFAULT_SOURCE_DIR / "promotions.csv", self.source / "promotions.csv")
                fields, rows = self.read_rows("promotions")
                rows[0][key] = value
                self.write_rows("promotions", fields, rows)
                with self.assertRaisesRegex(DataImportError, "promotions.csv, linha"):
                    import_catalog(self.source, self.database)

    def test_missing_file_invalid_header_or_empty_catalog_does_not_create_database(self):
        missing_database = self.root / "not-created.sqlite3"
        with self.assertRaises(DataImportError):
            import_catalog(self.root / "missing", missing_database)
        self.assertFalse(missing_database.exists())
        path = self.source / "products.csv"
        for content in ("wrong_header\nvalue\n", path.read_text(encoding="utf-8-sig").splitlines()[0] + "\n"):
            with self.subTest(content=content[:30]):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(DataImportError):
                    import_catalog(self.source, missing_database)
                self.assertFalse(missing_database.exists())

    def test_missing_database_is_not_created_by_queries(self):
        path = self.root / "missing.sqlite3"
        with self.assertRaisesRegex(CatalogError, "emporio.import_data"):
            Catalog(path).list_categories()
        self.assertFalse(path.exists())

    def test_query_connection_is_read_only(self):
        with closing(connect_database(self.database)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE products SET price_cents = 0")


class MoneyConversionTests(unittest.TestCase):
    def test_accepts_exact_amounts(self):
        for value, expected in (("599.9", 59990), ("10.00", 1000), (Decimal("0.01"), 1), ("0", 0)):
            with self.subTest(value=value):
                self.assertEqual(brl_to_cents(value), expected)

    def test_rejects_ambiguous_nonfinite_or_inexact_amounts(self):
        for value in ("-1", "NaN", "Infinity", "1,50", "1.001", "1e1000000", "1e-1000000", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                brl_to_cents(value)


if __name__ == "__main__":
    unittest.main()
