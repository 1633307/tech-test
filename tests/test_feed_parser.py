"""
Pruebas unitarias para el FeedParser.
Verifica la gestión de anomalías detectadas en los feeds de Rovira.
"""

from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from src.infrastructure.csv.feed_parser import FeedParser


class TestFeedParser(unittest.TestCase):
    """Validación de casos borde y trampas del feed."""

    def setUp(self):
        self.parser = FeedParser()

    def test_parses_clean_feed(self):
        content = (
            "product_id,title,price,store_id\n"
            "001,Faro izquierdo,50.00,1|2\n"
            "002,Piloto trasero,25.50,3\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            res = self.parser.parse_file(temp_path)
            self.assertEqual(len(res.products), 2)
            self.assertEqual(len(res.errors), 0)
            self.assertEqual(res.products[0].store_ids, [1, 2])
            self.assertEqual(res.products[0].price, Decimal("50.00"))
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_handles_empty_lines_and_spaces_in_store_id(self):
        content = (
            "product_id,title,price,store_id\n"
            "\n"
            "001,Faro izquierdo,50.00,  2 | 3  \n"
            "\n"
            "002,Piloto trasero,25.50,1\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            res = self.parser.parse_file(temp_path)
            self.assertEqual(len(res.products), 2)
            self.assertEqual(res.empty_lines_skipped, 2)
            self.assertEqual(res.products[0].store_ids, [2, 3])
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_comma_price_records_error_without_failing_other_products(self):
        content = (
            "product_id,title,price,store_id\n"
            "001,Pieza buena,10.00,1\n"
            '002,Pieza con coma,"443,90",3\n'
            "003,Otra pieza buena,20.00,2\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            res = self.parser.parse_file(temp_path)
            self.assertEqual(len(res.products), 2)
            self.assertEqual(len(res.errors), 1)
            self.assertIn("coma", res.errors[0].reason)
            self.assertEqual(res.products[0].product_id, "001")
            self.assertEqual(res.products[1].product_id, "003")
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_truncates_title_to_80_chars(self):
        long_title = "A" * 120
        content = f"product_id,title,price,store_id\n001,{long_title},10.00,1\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            res = self.parser.parse_file(temp_path)
            self.assertEqual(len(res.products), 1)
            self.assertEqual(len(res.products[0].title), 80)
        finally:
            Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
