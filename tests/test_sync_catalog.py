"""
Pruebas unitarias para el caso de uso SyncCatalogUseCase.
Verifica las 5 reglas clave de negocio de Rovira y Piezalia.
"""

from decimal import Decimal
import unittest
from unittest.mock import MagicMock

from src.application.sync_catalog import SyncCatalogUseCase
from src.config import AccountCredentials
from src.domain.exceptions import TokenExpiredError
from src.domain.models import Listing, Product


class TestSyncCatalogUseCase(unittest.TestCase):
    """Batería de pruebas de sincronización y reconciliación."""

    def setUp(self):
        self.mock_product_repo = MagicMock()
        self.mock_listing_repo = MagicMock()
        self.mock_sync_log_repo = MagicMock()
        self.mock_portal_client = MagicMock()

        self.accounts = {
            1: AccountCredentials(1, "tok-1"),
        }

        self.use_case = SyncCatalogUseCase(
            product_repo=self.mock_product_repo,
            listing_repo=self.mock_listing_repo,
            sync_log_repo=self.mock_sync_log_repo,
            portal_client=self.mock_portal_client,
            accounts=self.accounts,
        )

    def test_sync_creates_listing_when_missing(self):
        """Pieza en catálogo que no tiene anuncio debe crearse (POST)."""
        self.mock_product_repo.get_all_active.return_value = [
            Product("SKU-100", "Retrovisor", Decimal("45.00"), [1]),
        ]
        self.mock_portal_client.get_listings.return_value = []
        self.mock_portal_client.create_listing.return_value = Listing(
            "L1", 1, "SKU-100", "Retrovisor", Decimal("45.00")
        )

        summary = self.use_case.execute()

        self.assertEqual(summary.total_created, 1)
        self.mock_portal_client.create_listing.assert_called_once_with(
            account_id=1,
            sku="SKU-100",
            title="Retrovisor",
            price=Decimal("45.00"),
        )
        self.mock_listing_repo.upsert_listing.assert_called_once()

    def test_sync_updates_listing_when_price_or_title_changed(self):
        """Pieza que ya existe pero con cambio de precio o título debe actualizarse (PUT) sin borrarla."""
        self.mock_product_repo.get_all_active.return_value = [
            Product("SKU-100", "Retrovisor Nuevo", Decimal("55.00"), [1]),
        ]
        existing_listing = Listing("L10", 1, "SKU-100", "Retrovisor Antiguo", Decimal("45.00"))
        self.mock_portal_client.get_listings.return_value = [existing_listing]
        self.mock_portal_client.update_listing.return_value = Listing(
            "L10", 1, "SKU-100", "Retrovisor Nuevo", Decimal("55.00")
        )

        summary = self.use_case.execute()

        self.assertEqual(summary.total_updated, 1)
        self.mock_portal_client.update_listing.assert_called_once_with(
            account_id=1,
            listing_id="L10",
            title="Retrovisor Nuevo",
            price=Decimal("55.00"),
        )
        self.mock_portal_client.delete_listing.assert_not_called()

    def test_sync_skips_put_when_data_is_identical(self):
        """Optimización: si el anuncio ya tiene el mismo título y precio, no se llama a PUT."""
        self.mock_product_repo.get_all_active.return_value = [
            Product("SKU-100", "Retrovisor", Decimal("50.00"), [1]),
        ]
        existing_listing = Listing("L10", 1, "SKU-100", "Retrovisor", Decimal("50.00"))
        self.mock_portal_client.get_listings.return_value = [existing_listing]

        summary = self.use_case.execute()

        self.assertEqual(summary.total_unchanged, 1)
        self.assertEqual(summary.total_updated, 0)
        self.mock_portal_client.update_listing.assert_not_called()
        self.mock_portal_client.create_listing.assert_not_called()
        self.mock_portal_client.delete_listing.assert_not_called()

    def test_sync_deletes_listing_when_product_removed_from_feed(self):
        """Pieza vendida o que ya no está en el catálogo debe retirarse (DELETE)."""
        # Catálogo activo no tiene la pieza SKU-999
        self.mock_product_repo.get_all_active.return_value = []
        existing_listing = Listing("L20", 1, "SKU-999", "Pieza vendida", Decimal("30.00"))
        self.mock_portal_client.get_listings.return_value = [existing_listing]

        summary = self.use_case.execute()

        self.assertEqual(summary.total_deleted, 1)
        self.mock_portal_client.delete_listing.assert_called_once_with(
            account_id=1,
            listing_id="L20",
        )
        self.mock_listing_repo.delete_listing.assert_called_once_with("L20")

    def test_sync_never_touches_manual_listings(self):
        """Regla de negocio 3: Jordi publica anuncios a mano (sku is None) que jamás se tocan."""
        self.mock_product_repo.get_all_active.return_value = []
        manual_listing = Listing("L99", 1, None, "Lote tornillos Jordi", Decimal("10.00"))
        self.mock_portal_client.get_listings.return_value = [manual_listing]

        summary = self.use_case.execute()

        # No debe ni borrarse ni modificarse
        self.assertEqual(summary.total_deleted, 0)
        self.assertEqual(summary.total_updated, 0)
        self.mock_portal_client.delete_listing.assert_not_called()
        self.mock_portal_client.update_listing.assert_not_called()

    def test_sync_isolates_account_failures_and_continues(self):
        """Si la cuenta 2 tiene el token expirado, se registra el fallo y la cuenta 1 sincroniza bien."""
        self.use_case._accounts = {
            1: AccountCredentials(1, "tok-1"),
            2: AccountCredentials(2, "tok-2"),
        }
        self.mock_product_repo.get_all_active.return_value = [
            Product("SKU-1", "Pieza Cuenta 1", Decimal("20.00"), [1]),
            Product("SKU-2", "Pieza Cuenta 2", Decimal("30.00"), [2]),
        ]

        def fake_get_listings(account_id):
            if account_id == 2:
                raise TokenExpiredError(account_id=2, detail="Token caducado")
            return []

        self.mock_portal_client.get_listings.side_effect = fake_get_listings
        self.mock_portal_client.create_listing.return_value = Listing(
            "L1", 1, "SKU-1", "Pieza Cuenta 1", Decimal("20.00")
        )

        summary = self.use_case.execute()

        # Cuenta 1 se creó con éxito
        self.assertEqual(summary.total_created, 1)
        # Cuenta 2 registró el error de token expirado
        self.assertTrue(summary.results_by_account[2].token_expired)
        self.assertEqual(summary.total_errors, 1)
        self.mock_sync_log_repo.log.assert_called()


if __name__ == "__main__":
    unittest.main()
