"""
Cliente HTTP para la API de Piezalia (Capa de Infraestructura).

Gestiona de forma resiliente la comunicación con el marketplace:
1. Autenticación Bearer individual por cuenta usando `accounts.csv`.
2. Gestión de 401 `token_expired`: Se detecta de inmediato y lanza `TokenExpiredError`.
   No se reintenta (la regla de negocio especifica que el cliente debe renovar en el portal).
3. Gestión de 429 `rate_limited`: Respeta la cabecera `Retry-After` y reintenta.
4. Gestión de 503 `unavailable`: Fallo transitorio; reintenta con backoff exponencial.
5. Gestión de 504 `gateway_timeout`: La operación puede o no haberse aplicado en Piezalia.
   El cliente comprueba el estado remoto para confirmar si la mutación surtió efecto.
6. Paginación completa en `GET /accounts/{account}/listings` hasta agotar `next_page`.
"""

from decimal import Decimal
import logging
import time
from typing import Any, Dict, List, Optional
import requests

from src.config import AccountCredentials
from src.domain.exceptions import PortalApiError, TokenExpiredError
from src.domain.models import Listing

logger = logging.getLogger(__name__)


class PiezaliaClient:
    """
    Cliente oficial para interactuar con la API REST de Piezalia.
    """

    def __init__(
        self,
        base_url: str,
        accounts: Dict[int, AccountCredentials],
        max_retries: int = 5,
        base_backoff_sec: float = 0.5,
        timeout_sec: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._accounts = accounts
        self._max_retries = max_retries
        self._base_backoff = base_backoff_sec
        self._timeout = timeout_sec
        self._session = requests.Session()

    def _get_token(self, account_id: int) -> str:
        """Obtiene el token configurado para una cuenta o falla si no existe."""
        acc = self._accounts.get(account_id)
        if not acc:
            raise PortalApiError(
                status_code=404,
                error_code="account_not_configured",
                detail=f"La cuenta {account_id} no está en accounts.csv",
            )
        return acc.token

    def _request(
        self,
        method: str,
        path: str,
        account_id: int,
        json_data: Optional[Dict[str, Any]] = None,
        sku_for_recovery: Optional[str] = None,
    ) -> requests.Response:
        """
        Ejecuta una petición HTTP contra Piezalia con reintentos y tolerancia a fallos.
        """
        url = f"{self._base_url}{path}"
        token = self._get_token(account_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        attempts = 0
        while True:
            attempts += 1
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if attempts > self._max_retries:
                    raise PortalApiError(
                        status_code=500,
                        error_code="network_error",
                        detail=f"Fallo de conexión tras {attempts} intentos: {exc}",
                    )
                sleep_time = self._base_backoff * (2 ** (attempts - 1))
                logger.warning(
                    "Error de red con Piezalia (%s %s). Reintentando en %.1fs: %s",
                    method,
                    path,
                    sleep_time,
                    exc,
                )
                time.sleep(sleep_time)
                continue

            # Caso 1: Éxito (2xx)
            if 200 <= response.status_code < 300:
                return response

            # Analizar cuerpo de error devuelto por Piezalia: {"error": "...", "detail": "..."}
            error_code = "unknown_error"
            detail = response.text
            try:
                err_json = response.json()
                if isinstance(err_json, dict):
                    error_code = err_json.get("error", error_code)
                    detail = err_json.get("detail", detail)
            except ValueError:
                pass

            # Caso 2: Token expirado (401 token_expired)
            if response.status_code == 401 and error_code == "token_expired":
                logger.error(
                    "El token de la cuenta %d ha caducado. Requiere renovación manual en Piezalia.",
                    account_id,
                )
                raise TokenExpiredError(account_id=account_id, detail=detail)

            # Caso 3: Rate Limiting (429 rate_limited)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 1))
                logger.warning(
                    "Rate limit alcanzado en cuenta %d (%s). Esperando %d seg (Retry-After)...",
                    account_id,
                    path,
                    retry_after,
                )
                time.sleep(retry_after)
                continue

            # Caso 4: Fallo transitorio del servidor (503 unavailable)
            if response.status_code == 503:
                if attempts > self._max_retries:
                    raise PortalApiError(503, error_code, detail)
                sleep_time = self._base_backoff * (2 ** (attempts - 1))
                logger.warning(
                    "Piezalia respondió 503 unavailable en cuenta %d. Reintento %d/%d en %.1fs...",
                    account_id,
                    attempts,
                    self._max_retries,
                    sleep_time,
                )
                time.sleep(sleep_time)
                continue

            # Caso 5: Gateway Timeout (504 gateway_timeout)
            if response.status_code == 504:
                logger.warning(
                    "Piezalia respondió 504 gateway_timeout en %s %s. Verificando si la operación se aplicó...",
                    method,
                    path,
                )
                # En 504 la mutación puede haberse aplicado. Comprobamos según el método:
                if method == "POST" and sku_for_recovery:
                    # Comprobar si el SKU ya existe en la cuenta
                    existing = self._find_listing_by_sku(account_id, sku_for_recovery)
                    if existing:
                        logger.info("Recuperación 504 exitosa: El anuncio %s ya fue creado.", existing.listing_id)
                        # Fabricamos una respuesta exitosa
                        fake_resp = requests.Response()
                        fake_resp.status_code = 201
                        fake_resp._content = response._content
                        return fake_resp
                elif method == "DELETE":
                    # Si al consultar la lista ya no está, se aplicó con éxito
                    listing_id = path.rstrip("/").split("/")[-1]
                    if not self._check_listing_exists(account_id, listing_id):
                        logger.info("Recuperación 504 exitosa: El anuncio %s fue retirado.", listing_id)
                        fake_resp = requests.Response()
                        fake_resp.status_code = 204
                        return fake_resp

                if attempts > self._max_retries:
                    raise PortalApiError(504, error_code, detail)
                time.sleep(self._base_backoff * attempts)
                continue

            # Cualquier otro código de error (404, 422, etc.) no es reintentable
            raise PortalApiError(response.status_code, error_code, detail)

    def get_listings(self, account_id: int) -> List[Listing]:
        """
        Recupera la lista íntegra de anuncios de una cuenta consumiendo todas las páginas.
        """
        all_listings: List[Listing] = []
        page = 1

        while page is not None:
            resp = self._request("GET", f"/accounts/{account_id}/listings?page={page}", account_id=account_id)
            data = resp.json()

            for item in data.get("items", []):
                all_listings.append(
                    Listing(
                        listing_id=item["listing_id"],
                        account_id=int(item["account"]),
                        sku=item.get("sku"),
                        title=item["title"],
                        price=Decimal(str(item["price"])),
                    )
                )

            page = data.get("next_page")

        return all_listings

    def create_listing(self, account_id: int, sku: str, title: str, price: Decimal) -> Listing:
        """
        Publica un nuevo anuncio en la cuenta indicada.
        """
        payload = {
            "sku": sku,
            "title": title,
            "price": f"{price:.2f}",
        }
        resp = self._request(
            method="POST",
            path=f"/accounts/{account_id}/listings",
            account_id=account_id,
            json_data=payload,
            sku_for_recovery=sku,
        )
        data = resp.json()
        return Listing(
            listing_id=data["listing_id"],
            account_id=int(data["account"]),
            sku=data.get("sku"),
            title=data["title"],
            price=Decimal(str(data["price"])),
        )

    def update_listing(
        self, account_id: int, listing_id: str, title: str, price: Decimal
    ) -> Listing:
        """
        Actualiza el título y precio de un anuncio existente sin cambiar su ID ni SKU.
        """
        payload = {
            "title": title,
            "price": f"{price:.2f}",
        }
        resp = self._request(
            method="PUT",
            path=f"/accounts/{account_id}/listings/{listing_id}",
            account_id=account_id,
            json_data=payload,
        )
        data = resp.json()
        return Listing(
            listing_id=data["listing_id"],
            account_id=int(data["account"]),
            sku=data.get("sku"),
            title=data["title"],
            price=Decimal(str(data["price"])),
        )

    def delete_listing(self, account_id: int, listing_id: str) -> None:
        """
        Retira un anuncio de la cuenta indicada en Piezalia.
        """
        self._request(
            method="DELETE",
            path=f"/accounts/{account_id}/listings/{listing_id}",
            account_id=account_id,
        )

    def _find_listing_by_sku(self, account_id: int, sku: str) -> Optional[Listing]:
        """Búsqueda auxiliar de un SKU para recuperaciones tras 504."""
        try:
            listings = self.get_listings(account_id)
            for l in listings:
                if l.sku == sku:
                    return l
        except Exception:
            pass
        return None

    def _check_listing_exists(self, account_id: int, listing_id: str) -> bool:
        """Comprueba si un listing_id sigue existiendo en la cuenta."""
        try:
            listings = self.get_listings(account_id)
            return any(l.listing_id == listing_id for l in listings)
        except Exception:
            return True
