"""
Caso de uso: Consulta de estado de una pieza para soporte (Marta).

Proporciona una respuesta inmediata, clara y sin tecnicismos cuando Jordi
llama preguntando por qué una pieza no está en una nave específica (ej. cuenta 4).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.database.repositories import (
        ListingRepository,
        ProductRepository,
        SyncLogRepository,
    )


class ProductStatusUseCase:
    """
    Diagnostica y formatea el estado de cualquier pieza del catálogo de Desguaces Rovira.
    """

    def __init__(
        self,
        product_repo: ProductRepository,
        listing_repo: ListingRepository,
        sync_log_repo: SyncLogRepository,
    ):
        self._product_repo = product_repo
        self._listing_repo = listing_repo
        self._sync_log_repo = sync_log_repo

    def get_status_data(self, product_id: str) -> Dict[str, Any]:
        """
        Recopila todos los datos estructurados de la pieza, sus anuncios y auditoría.
        """
        prod_data = self._product_repo.get_by_id(product_id)
        listings = self._listing_repo.get_by_sku(product_id)
        listings_by_account = {l.account_id: l for l in listings}
        recent_logs = self._sync_log_repo.get_recent_by_product(product_id, limit=5)

        if not prod_data:
            return {
                "product_found": False,
                "product_id": product_id,
                "detail": f"La referencia '{product_id}' no existe en el catálogo importado de Rovira.",
                "listings": [
                    {
                        "listing_id": l.listing_id,
                        "account_id": l.account_id,
                        "title": l.title,
                        "price": str(l.price),
                    }
                    for l in listings
                ],
            }

        store_ids = prod_data["store_ids"]
        is_active = prod_data["is_active"]

        # Evaluamos el estado en cada una de las 4 cuentas de Piezalia
        accounts_status = {}
        for acc_id in [1, 2, 3, 4]:
            should_be_in_acc = (acc_id in store_ids) and is_active
            listing = listings_by_account.get(acc_id)

            # Buscar posibles errores recientes de esta pieza en esta cuenta
            acc_logs = [log for log in recent_logs if log["account_id"] == acc_id]
            last_log = acc_logs[0] if acc_logs else None

            # Buscar si la cuenta en general tiene error de token
            acc_errors = self._sync_log_repo.get_recent_errors_by_account(acc_id, limit=1)
            token_expired_error = any("token" in (e.get("detail") or "").lower() for e in acc_errors)

            if listing and should_be_in_acc:
                status_code = "PUBLICADO"
                msg = f"Publicado correctamente (Anuncio: {listing.listing_id}, Precio en Piezalia: {listing.price} €)."
                if str(listing.price) != str(prod_data["price"]):
                    msg += f" (Pendiente actualizar precio en próximo sync: catálogo pide {prod_data['price']} €)."
            elif listing and not should_be_in_acc:
                status_code = "PENDIENTE_RETIRAR"
                msg = f"Publicado actualmente ({listing.listing_id}), pero la pieza ya no está asignada a esta cuenta en el feed. Se retirará en el próximo sync."
            elif not listing and should_be_in_acc:
                status_code = "NO_PUBLICADO"
                if token_expired_error:
                    msg = f"El token de la cuenta {acc_id} ha caducado en Piezalia. Jordi debe renovar el token desde el portal."
                elif last_log and last_log["status"] == "failed":
                    msg = f"Fallo al publicar: {last_log.get('detail')}."
                else:
                    msg = "Pendiente de publicación en la próxima sincronización horaria."
            else:
                status_code = "NO_ASIGNADO"
                msg = f"Jordi no ha seleccionado la cuenta {acc_id} en el feed (cuentas deseadas: {store_ids})."

            accounts_status[acc_id] = {
                "account_id": acc_id,
                "should_be_published": should_be_in_acc,
                "is_published": listing is not None,
                "listing_id": listing.listing_id if listing else None,
                "published_price": str(listing.price) if listing else None,
                "status_code": status_code,
                "explanation": msg,
            }

        return {
            "product_found": True,
            "product_id": prod_data["product_id"],
            "title": prod_data["title"],
            "price": str(prod_data["price"]),
            "store_ids": store_ids,
            "is_active": is_active,
            "last_feed_file": prod_data["last_feed_file"],
            "imported_at": str(prod_data["imported_at"]),
            "accounts": accounts_status,
            "recent_logs": recent_logs,
        }

    def execute(self, product_id: str) -> str:
        """
        Genera el informe formateado para consola que Marta puede leer directamente a Jordi.
        """
        data = self.get_status_data(product_id)

        if not data.get("product_found"):
            return (
                f"\n❌ [SOPORTE MARTA] Pieza no encontrada\n"
                f"Referencia: {product_id}\n"
                f"Detalle: {data.get('detail')}\n"
            )

        active_str = "SÍ (A la venta)" if data["is_active"] else "NO (Vendida / Retirada)"
        lines = [
            "",
            "=" * 70,
            f"  INFORME DE SOPORTE PARA MARTA — PIEZA: {data['product_id']}",
            "=" * 70,
            f"Título en catálogo:  {data['title']}",
            f"Precio en catálogo:  {data['price']} €",
            f"A la venta:          {active_str}",
            f"Naves asignadas:     Cuentas {data['store_ids']}",
            f"Último feed:         {data['last_feed_file']} ({data['imported_at']})",
            "-" * 70,
            "  ESTADO EN PIEZALIA POR CUENTA (NAVE):",
            "-" * 70,
        ]

        for acc_id in [1, 2, 3, 4]:
            acc = data["accounts"][acc_id]
            badge = "✅" if acc["status_code"] == "PUBLICADO" else ("⚠️" if "PENDIENTE" in acc["status_code"] else "❌")
            lines.append(f"  Cuenta {acc_id}: {badge} [{acc['status_code']}]")
            lines.append(f"     Explicación: {acc['explanation']}")

        # Si hay logs recientes
        if data.get("recent_logs"):
            lines.append("-" * 70)
            lines.append("  HISTORIAL RECIENTE DE INTENTOS DE SYNC:")
            for log in data["recent_logs"][:3]:
                lines.append(f"   * Cuenta {log['account_id']} | Acción: {log['action']} | Estado: {log['status']} | {log['detail']}")

        lines.append("=" * 70)
        return "\n".join(lines)
