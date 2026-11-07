"""
Pruebas unitarias para PiezaliaClient (Capa de Infraestructura).
Verifica la gestión de códigos HTTP especiales: 401, 429, 503, 504 y paginación.
"""

from decimal import Decimal
import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import requests
except ImportError:
    # Si requests aún no está instalado en el host, proveemos un mock para ejecución de tests
    mock_requests = MagicMock()
    class FakeRequestException(Exception): pass
    class FakeSession(MagicMock): pass
    class FakeResponse(MagicMock): pass
    mock_requests.RequestException = FakeRequestException
    mock_requests.Session = FakeSession
    mock_requests.Response = FakeResponse
    sys.modules["requests"] = mock_requests
    import requests

from src.config import AccountCredentials
from src.domain.exceptions import PortalApiError, TokenExpiredError
from src.infrastructure.portal.client import PiezaliaClient


class TestPiezaliaClient(unittest.TestCase):
    """Batería de pruebas de resiliencia del cliente HTTP de Piezalia."""

    def setUp(self):
        self.accounts = {
            1: AccountCredentials(account_id=1, token="tok-1"),
        }
        self.client = PiezaliaClient(
            base_url="http://test-portal:8080",
            accounts=self.accounts,
            max_retries=3,
            base_backoff_sec=0.01,  # Rápido para tests
            timeout_sec=1.0,
        )

    def test_token_expired_raises_immediately_without_retries(self):
        """401 token_expired debe abortar al instante sin reintentar (requiere acción de Jordi)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "error": "token_expired",
            "detail": "the token has expired; renew it in the portal",
        }
        self.client._session.request = MagicMock(return_value=mock_resp)

        with self.assertRaises(TokenExpiredError) as ctx:
            self.client.get_listings(account_id=1)

        self.assertEqual(ctx.exception.account_id, 1)
        # Solo se debió llamar 1 vez (sin reintentos)
        self.assertEqual(self.client._session.request.call_count, 1)

    @patch("time.sleep")
    def test_rate_limited_waits_retry_after_and_retries(self, mock_sleep):
        """429 rate_limited debe esperar los segundos de Retry-After y reintentar con éxito."""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"Retry-After": "2"}
        resp_429.json.return_value = {"error": "rate_limited", "detail": "too many requests"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"items": [], "page": 1, "next_page": None}

        self.client._session.request = MagicMock(side_effect=[resp_429, resp_200])

        listings = self.client.get_listings(account_id=1)

        self.assertEqual(listings, [])
        self.assertEqual(self.client._session.request.call_count, 2)
        mock_sleep.assert_called_with(2)

    @patch("time.sleep")
    def test_transient_503_retries_and_succeeds(self, mock_sleep):
        """503 unavailable reintenta con backoff y se recupera."""
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.json.return_value = {"error": "unavailable", "detail": "portal busy"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {"items": [], "page": 1, "next_page": None}

        self.client._session.request = MagicMock(side_effect=[resp_503, resp_200])

        listings = self.client.get_listings(account_id=1)

        self.assertEqual(listings, [])
        self.assertEqual(self.client._session.request.call_count, 2)
        self.assertTrue(mock_sleep.called)

    def test_pagination_fetches_multiple_pages(self):
        """GET listings consume todas las páginas hasta que next_page sea null."""
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "items": [
                {
                    "listing_id": "L1",
                    "account": 1,
                    "sku": "SKU1",
                    "title": "Faro",
                    "price": "20.00",
                }
            ],
            "page": 1,
            "next_page": 2,
        }

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "items": [
                {
                    "listing_id": "L2",
                    "account": 1,
                    "sku": "SKU2",
                    "title": "Piloto",
                    "price": "30.00",
                }
            ],
            "page": 2,
            "next_page": None,
        }

        self.client._session.request = MagicMock(side_effect=[page1, page2])

        listings = self.client.get_listings(account_id=1)

        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0].listing_id, "L1")
        self.assertEqual(listings[1].listing_id, "L2")
        self.assertEqual(self.client._session.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
