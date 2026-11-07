"""
Caso de uso: Sincronización del catálogo de Desguaces Rovira con Piezalia.

Implementa la reconciliación entre el catálogo activo en PostgreSQL y los anuncios
publicados en cada una de las 4 cuentas de Piezalia (una por nave de Rovira):
1. Procesamiento independiente por cuenta: Si una nave tiene el token expirado (ej. cuenta 4),
   se registra el incidente para Marta y se continúa sincronizando las demás naves.
2. Respeto absoluto a los anuncios manuales de Jordi: Si `sku is None`, no se tocan.
3. Actualizar antes que borrar: Se mantiene el `listing_id` original para conservar visitas
   y posicionamiento en Piezalia.
4. Optimización de llamadas: Solo se ejecuta PUT si el precio o título han cambiado.
5. Retirada inmediata de piezas vendidas: Si una pieza ya no está en el feed, se retira
   cuanto antes para evitar penalizaciones del marketplace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import logging
from typing import Dict, List, Optional, Set, TYPE_CHECKING

from src.domain.exceptions import TokenExpiredError
from src.domain.models import Listing, Product

if TYPE_CHECKING:
    from src.config import AccountCredentials
    from src.infrastructure.database.repositories import (
        ListingRepository,
        ProductRepository,
        SyncLogRepository,
    )
    from src.infrastructure.portal.client import PiezaliaClient

logger = logging.getLogger(__name__)


@dataclass
class AccountSyncResult:
    """Resultado de la sincronización de una cuenta individual."""
    account_id: int
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    errors: int = 0
    token_expired: bool = False
    detail: str = "OK"


@dataclass
class SyncSummary:
    """Resumen global del proceso de sincronización."""
    total_accounts: int
    results_by_account: Dict[int, AccountSyncResult] = field(default_factory=dict)
    total_created: int = 0
    total_updated: int = 0
    total_deleted: int = 0
    total_unchanged: int = 0
    total_errors: int = 0


class SyncCatalogUseCase:
    """
    Coordina la sincronización de todas las cuentas de Rovira con Piezalia.
    """

    def __init__(
        self,
        product_repo: ProductRepository,
        listing_repo: ListingRepository,
        sync_log_repo: SyncLogRepository,
        portal_client: PiezaliaClient,
        accounts: Dict[int, AccountCredentials],
    ):
        self._product_repo = product_repo
        self._listing_repo = listing_repo
        self._sync_log_repo = sync_log_repo
        self._portal_client = portal_client
        self._accounts = accounts

    def execute(self) -> SyncSummary:
        """
        Ejecuta el ciclo de sincronización sobre todas las cuentas configuradas.
        """
        logger.info("Iniciando sincronización de catálogo con Piezalia...")

        # 1. Obtener todas las piezas actualmente activas en el catálogo
        active_products = self._product_repo.get_all_active()
        logger.info("Total de piezas activas en catálogo: %d", len(active_products))

        summary = SyncSummary(total_accounts=len(self._accounts))

        # 2. Sincronizar cada cuenta de forma aislada
        for account_id in sorted(self._accounts.keys()):
            logger.info("--- Sincronizando Cuenta %d ---", account_id)
            acc_result = self._sync_account(account_id, active_products)
            summary.results_by_account[account_id] = acc_result

            summary.total_created += acc_result.created
            summary.total_updated += acc_result.updated
            summary.total_deleted += acc_result.deleted
            summary.total_unchanged += acc_result.unchanged
            summary.total_errors += acc_result.errors

        logger.info(
            "Sincronización completada: %d creados, %d actualizados, %d retirados, "
            "%d sin cambios, %d errores.",
            summary.total_created,
            summary.total_updated,
            summary.total_deleted,
            summary.total_unchanged,
            summary.total_errors,
        )
        return summary

    def _sync_account(self, account_id: int, active_products: List[Product]) -> AccountSyncResult:
        """Sincroniza una cuenta concreta con Piezalia."""
        result = AccountSyncResult(account_id=account_id)

        # Paso 1: Leer el estado actual de anuncios en Piezalia para esta cuenta
        try:
            remote_listings = self._portal_client.get_listings(account_id)
            # Actualizamos el espejo local de la base de datos
            self._listing_repo.replace_account_listings(account_id, remote_listings)
        except TokenExpiredError as exc:
            result.token_expired = True
            result.errors += 1
            result.detail = f"Token expirado: {exc.detail}"
            logger.error("Cuenta %d omitida: Token expirado.", account_id)
            self._sync_log_repo.log(
                account_id=account_id,
                action="auth",
                status="failed",
                detail=f"Token expirado. Jordi debe renovar en el portal de Piezalia.",
            )
            return result
        except Exception as exc:
            result.errors += 1
            result.detail = f"Error al consultar anuncios: {exc}"
            logger.error("Error al obtener anuncios de cuenta %d: %s", account_id, exc)
            self._sync_log_repo.log(
                account_id=account_id,
                action="fetch_listings",
                status="failed",
                detail=str(exc),
            )
            return result

        # Paso 2: Clasificar los anuncios de Piezalia
        # REGLA CRÍTICA: Los anuncios con sku IS NULL son manuales de Jordi -> NO TOCAR
        existing_by_sku: Dict[str, List[Listing]] = {}
        manual_listings_count = 0

        for item in remote_listings:
            if item.sku is None:
                manual_listings_count += 1
                continue
            existing_by_sku.setdefault(item.sku, []).append(item)

        logger.info(
            "Cuenta %d: %d anuncios remotos (%d manuales de Jordi respetados, %d referencias de catálogo).",
            account_id,
            len(remote_listings),
            manual_listings_count,
            len(existing_by_sku),
        )

        # Paso 3: Identificar piezas que según el catálogo DEBEN estar en esta cuenta
        expected_in_account: Dict[str, Product] = {
            p.product_id: p
            for p in active_products
            if account_id in p.store_ids
        }

        # Paso 4: Reconciliación: altas y modificaciones
        for sku, product in expected_in_account.items():
            if sku not in existing_by_sku:
                # A) CREATE: No existe anuncio para esta pieza en esta cuenta
                self._handle_create(account_id, product, result)
            else:
                # B) UPDATE: Ya existe anuncio; verificamos si han cambiado título o precio
                primary_listing = existing_by_sku[sku][0]
                self._handle_update(account_id, product, primary_listing, result)

                # Si Piezalia tuviera anuncios duplicados accidentales para el mismo SKU,
                # retiramos los sobrantes para evitar doble venta
                for duplicate in existing_by_sku[sku][1:]:
                    self._handle_delete_duplicate(account_id, duplicate, result)

        # Paso 5: Reconciliación: bajas (DELETE)
        # Piezas que tienen anuncio en Piezalia pero ya no están a la venta en esta cuenta
        for sku, listings_list in existing_by_sku.items():
            if sku not in expected_in_account:
                for listing_to_delete in listings_list:
                    self._handle_delete(account_id, listing_to_delete, result)

        return result

    def _handle_create(
        self, account_id: int, product: Product, result: AccountSyncResult
    ) -> None:
        """Crea un anuncio nuevo en Piezalia y actualiza el espejo local."""
        try:
            new_listing = self._portal_client.create_listing(
                account_id=account_id,
                sku=product.product_id,
                title=product.title,
                price=product.price,
            )
            self._listing_repo.upsert_listing(new_listing)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=product.product_id,
                action="create",
                status="success",
                detail=f"Anuncio {new_listing.listing_id} publicado con éxito",
            )
            result.created += 1
            logger.info("Cuenta %d: Creado anuncio %s para SKU %s", account_id, new_listing.listing_id, product.product_id)
        except Exception as exc:
            result.errors += 1
            logger.error("Cuenta %d: Fallo al crear anuncio para SKU %s: %s", account_id, product.product_id, exc)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=product.product_id,
                action="create",
                status="failed",
                detail=str(exc),
            )

    def _handle_update(
        self,
        account_id: int,
        product: Product,
        existing: Listing,
        result: AccountSyncResult,
    ) -> None:
        """Actualiza el anuncio solo si cambiaron el título o el precio."""
        title_changed = product.title != existing.title
        price_changed = product.price != existing.price

        if not title_changed and not price_changed:
            # Optimización esencial: evitar peticiones innecesarias
            result.unchanged += 1
            return

        try:
            updated = self._portal_client.update_listing(
                account_id=account_id,
                listing_id=existing.listing_id,
                title=product.title,
                price=product.price,
            )
            self._listing_repo.upsert_listing(updated)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=product.product_id,
                action="update",
                status="success",
                detail=f"Anuncio {existing.listing_id} actualizado (precio: {existing.price}->{product.price})",
            )
            result.updated += 1
            logger.info("Cuenta %d: Actualizado anuncio %s (SKU %s)", account_id, existing.listing_id, product.product_id)
        except Exception as exc:
            result.errors += 1
            logger.error("Cuenta %d: Fallo al actualizar anuncio %s: %s", account_id, existing.listing_id, exc)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=product.product_id,
                action="update",
                status="failed",
                detail=str(exc),
            )

    def _handle_delete(
        self, account_id: int, listing: Listing, result: AccountSyncResult
    ) -> None:
        """Retira un anuncio de una pieza ya no disponible en esta cuenta."""
        try:
            self._portal_client.delete_listing(
                account_id=account_id,
                listing_id=listing.listing_id,
            )
            self._listing_repo.delete_listing(listing.listing_id)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=listing.sku,
                action="delete",
                status="success",
                detail=f"Anuncio {listing.listing_id} retirado (pieza ya no está a la venta en esta cuenta)",
            )
            result.deleted += 1
            logger.info("Cuenta %d: Retirado anuncio %s (SKU %s)", account_id, listing.listing_id, listing.sku)
        except Exception as exc:
            result.errors += 1
            logger.error("Cuenta %d: Fallo al retirar anuncio %s: %s", account_id, listing.listing_id, exc)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=listing.sku,
                action="delete",
                status="failed",
                detail=str(exc),
            )

    def _handle_delete_duplicate(
        self, account_id: int, duplicate: Listing, result: AccountSyncResult
    ) -> None:
        """Elimina un anuncio duplicado del mismo SKU."""
        try:
            self._portal_client.delete_listing(account_id, duplicate.listing_id)
            self._listing_repo.delete_listing(duplicate.listing_id)
            self._sync_log_repo.log(
                account_id=account_id,
                product_id=duplicate.sku,
                action="delete_duplicate",
                status="success",
                detail=f"Anuncio duplicado {duplicate.listing_id} retirado",
            )
            result.deleted += 1
        except Exception as exc:
            result.errors += 1
            logger.warning("Fallo al retirar duplicado %s: %s", duplicate.listing_id, exc)
