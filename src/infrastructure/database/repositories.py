"""
Repositorios de acceso a datos para PostgreSQL.

Implementa las operaciones de persistencia respetando Clean Architecture:
- ProductRepository: Almacenamiento y consulta del catálogo de Desguaces Rovira.
- ListingRepository: Espejo local de anuncios existentes en Piezalia.
- SyncLogRepository: Trazabilidad y auditoría de sincronizaciones para soporte (Marta).
"""

from decimal import Decimal
from typing import Dict, List, Optional
from psycopg2.extras import execute_values

from src.domain.models import Listing, Product
from src.infrastructure.database.connection import DatabaseConnectionFactory


class ProductRepository:
    """
    Repositorio para gestionar el catálogo de productos de Desguaces Rovira.
    Permite guardar lotes de productos y consultar tanto productos activos
    como el histórico de una pieza particular.
    """

    def __init__(self, db_factory: DatabaseConnectionFactory):
        self._db_factory = db_factory

    def count_active(self) -> int:
        """Devuelve el total de productos actualmente marcados como activos."""
        with self._db_factory.get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM products WHERE is_active = TRUE;")
            row = cur.fetchone()
            return row["total"] if row else 0

    def get_by_id(self, product_id: str) -> Optional[Dict]:
        """
        Obtiene la información completa de una pieza por su ID.
        Útil para el caso de uso `status` requerido por Marta.
        """
        with self._db_factory.get_cursor() as cur:
            cur.execute(
                """
                SELECT product_id, title, price, store_ids, is_active,
                       last_feed_file, imported_at, updated_at
                FROM products
                WHERE product_id = %s;
                """,
                (product_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_all_active(self) -> List[Product]:
        """Recupera todos los productos actualmente a la venta en el catálogo."""
        with self._db_factory.get_cursor() as cur:
            cur.execute(
                """
                SELECT product_id, title, price, store_ids
                FROM products
                WHERE is_active = TRUE;
                """
            )
            rows = cur.fetchall()
            return [
                Product(
                    product_id=r["product_id"],
                    title=r["title"],
                    price=Decimal(str(r["price"])),
                    store_ids=list(r["store_ids"]),
                )
                for r in rows
            ]

    def save_feed_catalog(self, products: List[Product], feed_file: str) -> Dict[str, int]:
        """
        Actualiza el catálogo completo a partir de un nuevo feed:
        1. Marca como inactivas (is_active = FALSE) las piezas que ya no vienen en el feed.
           (Regla de negocio: pieza que no viene ya no está a la venta).
        2. Inserta o actualiza (upsert) las piezas que sí vienen en el feed y las marca activas.

        Devuelve un resumen con el conteo de activas e inactivadas.
        """
        if not products:
            return {"active": 0, "deactivated": 0}

        feed_product_ids = [p.product_id for p in products]

        with self._db_factory.get_connection() as conn:
            with conn.cursor() as cur:
                # Paso 1: Inactivar piezas que antes estaban activas pero ya no vienen
                cur.execute(
                    """
                    UPDATE products
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE is_active = TRUE AND NOT (product_id = ANY(%s));
                    """,
                    (feed_product_ids,),
                )
                deactivated_count = cur.rowcount

                # Paso 2: Upsert de todas las piezas del nuevo feed
                records = [
                    (
                        p.product_id,
                        p.title,
                        p.price,
                        p.store_ids,
                        True,
                        feed_file,
                    )
                    for p in products
                ]

                upsert_sql = """
                    INSERT INTO products (
                        product_id, title, price, store_ids, is_active, last_feed_file,
                        imported_at, updated_at
                    )
                    VALUES %s
                    ON CONFLICT (product_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        price = EXCLUDED.price,
                        store_ids = EXCLUDED.store_ids,
                        is_active = TRUE,
                        last_feed_file = EXCLUDED.last_feed_file,
                        updated_at = NOW();
                """
                execute_values(cur, upsert_sql, records, page_size=1000)

        return {"active": len(products), "deactivated": deactivated_count}


class ListingRepository:
    """
    Repositorio para el espejo local de anuncios en Piezalia.
    Mantiene una copia actualizada de los anuncios publicados en cada cuenta.
    """

    def __init__(self, db_factory: DatabaseConnectionFactory):
        self._db_factory = db_factory

    def get_by_account(self, account_id: int) -> List[Listing]:
        """Obtiene todos los anuncios conocidos para una cuenta de Piezalia."""
        with self._db_factory.get_cursor() as cur:
            cur.execute(
                """
                SELECT listing_id, account_id, sku, title, price
                FROM listings
                WHERE account_id = %s;
                """,
                (account_id,),
            )
            rows = cur.fetchall()
            return [
                Listing(
                    listing_id=r["listing_id"],
                    account_id=r["account_id"],
                    sku=r["sku"],
                    title=r["title"],
                    price=Decimal(str(r["price"])),
                )
                for r in rows
            ]

    def get_by_sku(self, sku: str) -> List[Listing]:
        """Encuentra todos los anuncios asociados a un SKU en cualquiera de las cuentas."""
        with self._db_factory.get_cursor() as cur:
            cur.execute(
                """
                SELECT listing_id, account_id, sku, title, price
                FROM listings
                WHERE sku = %s
                ORDER BY account_id ASC;
                """,
                (sku,),
            )
            rows = cur.fetchall()
            return [
                Listing(
                    listing_id=r["listing_id"],
                    account_id=r["account_id"],
                    sku=r["sku"],
                    title=r["title"],
                    price=Decimal(str(r["price"])),
                )
                for r in rows
            ]

    def upsert_listing(self, listing: Listing) -> None:
        """Inserta o actualiza un anuncio individual en el espejo local."""
        with self._db_factory.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO listings (listing_id, account_id, sku, title, price, synced_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (listing_id) DO UPDATE SET
                        sku = EXCLUDED.sku,
                        title = EXCLUDED.title,
                        price = EXCLUDED.price,
                        synced_at = NOW();
                    """,
                    (
                        listing.listing_id,
                        listing.account_id,
                        listing.sku,
                        listing.title,
                        listing.price,
                    ),
                )

    def delete_listing(self, listing_id: str) -> None:
        """Elimina un anuncio del espejo local tras ser retirado de Piezalia."""
        with self._db_factory.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM listings WHERE listing_id = %s;", (listing_id,))

    def replace_account_listings(self, account_id: int, listings: List[Listing]) -> None:
        """
        Reemplaza en bloque todos los anuncios de una cuenta con el estado recién leído
        de la API de Piezalia.
        """
        with self._db_factory.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM listings WHERE account_id = %s;", (account_id,))
                if listings:
                    records = [
                        (l.listing_id, l.account_id, l.sku, l.title, l.price)
                        for l in listings
                    ]
                    execute_values(
                        cur,
                        """
                        INSERT INTO listings (listing_id, account_id, sku, title, price, synced_at)
                        VALUES %s;
                        """,
                        records,
                        page_size=1000,
                    )


class SyncLogRepository:
    """
    Repositorio de auditoría de sincronizaciones.
    Permite registrar cada acción o error y consultar el historial reciente de una pieza.
    """

    def __init__(self, db_factory: DatabaseConnectionFactory):
        self._db_factory = db_factory

    def log(
        self,
        account_id: int,
        action: str,
        status: str,
        product_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        """Inserta un registro en el log de auditoría."""
        with self._db_factory.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sync_log (product_id, account_id, action, status, detail, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW());
                    """,
                    (product_id, account_id, action, status, detail),
                )

    def get_recent_by_product(self, product_id: str, limit: int = 10) -> List[Dict]:
        """Recupera los últimos registros de sincronización de un producto concreto."""
        with self._db_factory.get_cursor() as cur:
            cur.execute(
                """
                SELECT id, product_id, account_id, action, status, detail, created_at
                FROM sync_log
                WHERE product_id = %s
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (product_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_recent_errors_by_account(self, account_id: int, limit: int = 5) -> List[Dict]:
        """Recupera los errores más recientes ocurridos en una cuenta."""
        with self._db_factory.get_cursor() as cur:
            cur.execute(
                """
                SELECT id, product_id, account_id, action, status, detail, created_at
                FROM sync_log
                WHERE account_id = %s AND status = 'failed'
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (account_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]
