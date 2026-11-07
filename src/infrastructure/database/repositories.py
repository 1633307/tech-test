"""
Repositorios de acceso a datos implementados con SQLAlchemy 2.0 ORM.

Mantiene el principio de inversión de dependencias de Clean Architecture:
- La capa de Dominio define las entidades (Product, Listing).
- Esta capa de Infraestructura soporta tanto PostgreSQL (vía pg_insert ON CONFLICT)
  como SQLite (vía sqlite_insert ON CONFLICT) para permitir ejecución inmediata sin Docker.
"""

from decimal import Decimal
import logging
from typing import Dict, List, Optional

from sqlalchemy import delete, func, select, update

from src.domain.models import Listing, Product
from src.infrastructure.database.connection import DatabaseConnectionFactory
from src.infrastructure.database.orm_models import ListingORM, ProductORM, SyncLogORM

logger = logging.getLogger(__name__)


class ProductRepository:
    """
    Repositorio ORM para gestionar el catálogo de productos de Desguaces Rovira.
    """

    def __init__(self, db_factory: DatabaseConnectionFactory):
        self._db_factory = db_factory

    def count_active(self) -> int:
        """Devuelve el número total de productos activos en el catálogo."""
        with self._db_factory.get_session() as session:
            stmt = select(func.count()).select_from(ProductORM).where(ProductORM.is_active.is_(True))
            return session.scalar(stmt) or 0

    def get_by_id(self, product_id: str) -> Optional[Dict]:
        """
        Obtiene los datos completos de una pieza por su ID.
        Retorna un diccionario con datos de auditoría para el caso de uso `status` de soporte.
        """
        with self._db_factory.get_session() as session:
            stmt = select(ProductORM).where(ProductORM.product_id == product_id)
            orm_prod = session.scalar(stmt)
            if not orm_prod:
                return None
            return {
                "product_id": orm_prod.product_id,
                "title": orm_prod.title,
                "price": Decimal(str(orm_prod.price)),
                "store_ids": list(orm_prod.store_ids),
                "is_active": orm_prod.is_active,
                "last_feed_file": orm_prod.last_feed_file,
                "imported_at": orm_prod.imported_at,
                "updated_at": orm_prod.updated_at,
            }

    def get_all_active(self) -> List[Product]:
        """Recupera todas las piezas que están activas para sincronización."""
        with self._db_factory.get_session() as session:
            stmt = select(ProductORM).where(ProductORM.is_active.is_(True))
            rows = session.scalars(stmt).all()
            return [r.to_domain() for r in rows]

    def save_feed_catalog(self, products: List[Product], feed_file: str) -> Dict[str, int]:
        """
        Persiste el feed completo usando upsert nativo (PostgreSQL o SQLite):
        1. Desactiva piezas que ya no vienen en el feed (regla de Rovira).
        2. Inserta o actualiza las piezas presentes en el feed y las marca activas.
        """
        if not products:
            return {"active": 0, "deactivated": 0}

        feed_product_ids = [p.product_id for p in products]

        with self._db_factory.get_session() as session:
            # 1. Inactivar productos no presentes en el nuevo feed
            deactivate_stmt = (
                update(ProductORM)
                .where(ProductORM.is_active.is_(True))
                .where(ProductORM.product_id.not_in(feed_product_ids))
                .values(is_active=False, updated_at=func.now())
            )
            res = session.execute(deactivate_stmt)
            deactivated_count = res.rowcount

            # 2. Upsert multi-dialecto (PostgreSQL vs SQLite)
            dialect_name = session.bind.dialect.name
            values = [
                {
                    "product_id": p.product_id,
                    "title": p.title,
                    "price": p.price,
                    "store_ids": p.store_ids,
                    "is_active": True,
                    "last_feed_file": feed_file,
                }
                for p in products
            ]

            if dialect_name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                stmt = pg_insert(ProductORM).values(values)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=[ProductORM.product_id],
                    set_={
                        "title": stmt.excluded.title,
                        "price": stmt.excluded.price,
                        "store_ids": stmt.excluded.store_ids,
                        "is_active": True,
                        "last_feed_file": stmt.excluded.last_feed_file,
                        "updated_at": func.now(),
                    },
                )
                session.execute(upsert_stmt)
            else:
                # SQLite o fallback genérico
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                stmt = sqlite_insert(ProductORM).values(values)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=[ProductORM.product_id],
                    set_={
                        "title": stmt.excluded.title,
                        "price": stmt.excluded.price,
                        "store_ids": stmt.excluded.store_ids,
                        "is_active": True,
                        "last_feed_file": stmt.excluded.last_feed_file,
                        "updated_at": func.now(),
                    },
                )
                session.execute(upsert_stmt)

        return {"active": len(products), "deactivated": deactivated_count}


class ListingRepository:
    """
    Repositorio ORM para el espejo local de anuncios de Piezalia en base de datos.
    """

    def __init__(self, db_factory: DatabaseConnectionFactory):
        self._db_factory = db_factory

    def get_by_account(self, account_id: int) -> List[Listing]:
        """Recupera todos los anuncios almacenados para una cuenta."""
        with self._db_factory.get_session() as session:
            stmt = select(ListingORM).where(ListingORM.account_id == account_id)
            rows = session.scalars(stmt).all()
            return [r.to_domain() for r in rows]

    def get_by_sku(self, sku: str) -> List[Listing]:
        """Busca anuncios en cualquier cuenta que coincidan con un SKU (referencia)."""
        with self._db_factory.get_session() as session:
            stmt = select(ListingORM).where(ListingORM.sku == sku).order_by(ListingORM.account_id)
            rows = session.scalars(stmt).all()
            return [r.to_domain() for r in rows]

    def upsert_listing(self, listing: Listing) -> None:
        """Inserta o actualiza un anuncio individual en la base de datos."""
        with self._db_factory.get_session() as session:
            dialect_name = session.bind.dialect.name
            values = {
                "listing_id": listing.listing_id,
                "account_id": listing.account_id,
                "sku": listing.sku,
                "title": listing.title,
                "price": listing.price,
            }

            if dialect_name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                stmt = pg_insert(ListingORM).values(**values)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=[ListingORM.listing_id],
                    set_={
                        "sku": stmt.excluded.sku,
                        "title": stmt.excluded.title,
                        "price": stmt.excluded.price,
                        "synced_at": func.now(),
                    },
                )
                session.execute(upsert_stmt)
            else:
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                stmt = sqlite_insert(ListingORM).values(**values)
                upsert_stmt = stmt.on_conflict_do_update(
                    index_elements=[ListingORM.listing_id],
                    set_={
                        "sku": stmt.excluded.sku,
                        "title": stmt.excluded.title,
                        "price": stmt.excluded.price,
                        "synced_at": func.now(),
                    },
                )
                session.execute(upsert_stmt)

    def delete_listing(self, listing_id: str) -> None:
        """Elimina un anuncio del espejo local."""
        with self._db_factory.get_session() as session:
            stmt = delete(ListingORM).where(ListingORM.listing_id == listing_id)
            session.execute(stmt)

    def replace_account_listings(self, account_id: int, listings: List[Listing]) -> None:
        """Reemplaza la totalidad de anuncios de una cuenta con el estado remoto recibido."""
        with self._db_factory.get_session() as session:
            # Borrar anteriores
            session.execute(delete(ListingORM).where(ListingORM.account_id == account_id))
            # Insertar nuevos
            if listings:
                orm_objects = [ListingORM.from_domain(l) for l in listings]
                session.add_all(orm_objects)


class SyncLogRepository:
    """
    Repositorio ORM para auditar operaciones y errores de sincronización.
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
        """Registra un evento de sincronización para trazabilidad."""
        with self._db_factory.get_session() as session:
            entry = SyncLogORM(
                account_id=account_id,
                product_id=product_id,
                action=action,
                status=status,
                detail=detail,
            )
            session.add(entry)

    def get_recent_by_product(self, product_id: str, limit: int = 10) -> List[Dict]:
        """Recupera los últimos registros de sincronización de un producto (para soporte)."""
        with self._db_factory.get_session() as session:
            stmt = (
                select(SyncLogORM)
                .where(SyncLogORM.product_id == product_id)
                .order_by(SyncLogORM.created_at.desc())
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": r.id,
                    "product_id": r.product_id,
                    "account_id": r.account_id,
                    "action": r.action,
                    "status": r.status,
                    "detail": r.detail,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def get_recent_errors_by_account(self, account_id: int, limit: int = 5) -> List[Dict]:
        """Obtiene los fallos recientes en una cuenta para diagnósticos rápidos."""
        with self._db_factory.get_session() as session:
            stmt = (
                select(SyncLogORM)
                .where(SyncLogORM.account_id == account_id)
                .where(SyncLogORM.status == "failed")
                .order_by(SyncLogORM.created_at.desc())
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": r.id,
                    "product_id": r.product_id,
                    "account_id": r.account_id,
                    "action": r.action,
                    "status": r.status,
                    "detail": r.detail,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
