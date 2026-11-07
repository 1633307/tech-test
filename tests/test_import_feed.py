"""
Pruebas unitarias para el caso de uso ImportFeedUseCase.
Usa la biblioteca estándar unittest para ejecución sin dependencias externas.
"""

from decimal import Decimal
import unittest
from unittest.mock import MagicMock

from src.application.import_feed import ImportFeedUseCase
from src.domain.exceptions import TruncatedFeedError
from src.domain.models import Product
from src.infrastructure.csv.feed_parser import FeedParseResult, FeedParser


class TestImportFeedUseCase(unittest.TestCase):
    """Batería de pruebas para la importación y validación del feed."""

    def test_import_feed_successful(self):
        """Verifica que un feed válido se procese y persista correctamente."""
        mock_repo = MagicMock()
        mock_repo.count_active.return_value = 0
        mock_repo.save_feed_catalog.return_value = {"active": 2, "deactivated": 0}

        mock_parser = MagicMock(spec=FeedParser)
        mock_parser.parse_file.return_value = FeedParseResult(
            products=[
                Product("001", "Faro izquierdo", Decimal("50.00"), [1, 2]),
                Product("002", "Paragolpes delantero", Decimal("120.00"), [3]),
            ],
            errors=[],
            empty_lines_skipped=0,
            total_lines_read=3,
        )

        use_case = ImportFeedUseCase(
            product_repo=mock_repo,
            feed_parser=mock_parser,
            truncation_threshold=0.5,
        )

        summary = use_case.execute("dummy_feed.csv")

        self.assertEqual(summary.total_active, 2)
        self.assertEqual(summary.deactivated, 0)
        self.assertEqual(summary.parsing_errors, 0)
        mock_repo.save_feed_catalog.assert_called_once()

    def test_truncated_feed_raises_error_and_does_not_save(self):
        """
        Verifica que si el feed viene con menos productos del umbral (ej. 1 frente a 100),
        se lance TruncatedFeedError y NO se altere la base de datos.
        """
        mock_repo = MagicMock()
        mock_repo.count_active.return_value = 100  # Había 100 productos en el catálogo activo

        mock_parser = MagicMock(spec=FeedParser)
        mock_parser.parse_file.return_value = FeedParseResult(
            products=[
                Product("001", "Faro izquierdo", Decimal("50.00"), [1]),
            ],  # Solo viene 1 (1% del catálogo)
            errors=[],
            empty_lines_skipped=0,
            total_lines_read=2,
        )

        use_case = ImportFeedUseCase(
            product_repo=mock_repo,
            feed_parser=mock_parser,
            truncation_threshold=0.5,
        )

        with self.assertRaises(TruncatedFeedError) as ctx:
            use_case.execute("partial_feed.csv")

        self.assertIn("Feed posiblemente truncado", str(ctx.exception))
        # Fundamental: NO debe llamarse a save_feed_catalog
        mock_repo.save_feed_catalog.assert_not_called()


if __name__ == "__main__":
    unittest.main()
