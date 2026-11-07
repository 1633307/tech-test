"""
Pruebas unitarias para el caso de uso ProductStatusUseCase (Soporte Marta).
"""

from decimal import Decimal
import unittest
from unittest.mock import MagicMock

from src.application.product_status import ProductStatusUseCase
from src.domain.models import Listing


class TestProductStatusUseCase(unittest.TestCase):
    """Pruebas del informe de diagnóstico para soporte técnico."""

    def setUp(self):
        self.mock_product_repo = MagicMock()
        self.mock_listing_repo = MagicMock()
        self.mock_sync_log_repo = MagicMock()

        self.use_case = ProductStatusUseCase(
            product_repo=self.mock_product_repo,
            listing_repo=self.mock_listing_repo,
            sync_log_repo=self.mock_sync_log_repo,
        )

    def test_status_when_product_not_found(self):
        """Pieza inexistente devuelve mensaje claro para Marta."""
        self.mock_product_repo.get_by_id.return_value = None
        self.mock_listing_repo.get_by_sku.return_value = []
        self.mock_sync_log_repo.get_recent_by_product.return_value = []

        report = self.use_case.execute("NOEXISTE")
        self.assertIn("Pieza no encontrada", report)
        self.assertIn("NOEXISTE", report)

    def test_status_diagnoses_token_expired_on_account_4(self):
        """
        Escenario Jordi y Marta:
        Jordi pregunta por qué la pieza 8090 no está en su cuenta 4.
        El catálogo pide cuentas [3, 4], pero la cuenta 4 tiene token expirado.
        """
        self.mock_product_repo.get_by_id.return_value = {
            "product_id": "8090",
            "title": "MANDO ELEVALUNAS TRASERO DERECHO",
            "price": Decimal("18.13"),
            "store_ids": [3, 4],
            "is_active": True,
            "last_feed_file": "feed_dia1.csv",
            "imported_at": "2026-11-07 10:00:00",
            "updated_at": "2026-11-07 10:00:00",
        }
        # Solo publicado en cuenta 3
        self.mock_listing_repo.get_by_sku.return_value = [
            Listing("L100", 3, "8090", "MANDO ELEVALUNAS TRASERO DERECHO", Decimal("18.13"))
        ]
        self.mock_sync_log_repo.get_recent_by_product.return_value = []

        # Error en cuenta 4 por token expirado
        def fake_acc_errors(acc_id, limit=1):
            if acc_id == 4:
                return [{"detail": "Token expirado. Jordi debe renovar en el portal de Piezalia."}]
            return []

        self.mock_sync_log_repo.get_recent_errors_by_account.side_effect = fake_acc_errors

        report = self.use_case.execute("8090")

        # Verificaciones para Marta
        self.assertIn("MANDO ELEVALUNAS TRASERO DERECHO", report)
        self.assertIn("Cuenta 3: ✅ [PUBLICADO]", report)
        self.assertIn("Cuenta 4: ❌ [NO_PUBLICADO]", report)
        self.assertIn("token de la cuenta 4 ha caducado en Piezalia", report)
        self.assertIn("Jordi debe renovar", report)


if __name__ == "__main__":
    unittest.main()
