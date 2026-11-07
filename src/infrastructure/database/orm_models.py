"""
Modelos ORM de SQLAlchemy 2.0 (Capa de Infraestructura).

Implementa el patrón Data Mapper: estas clases representan las tablas en PostgreSQL,
manteniéndose desacopladas de las entidades puras de Dominio (Product, Listing).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import ARRAY, Boolean, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.domain.models import Listing, Product


class Base(DeclarativeBase):
    """Clase base declarativa para SQLAlchemy 2.0."""
    pass


class ProductORM(Base):
    """
    Tabla `products`: catálogo persistido a partir de los feeds de Rovira.
    """
    __tablename__ = "products"

    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    store_ids: Mapped[List[int]] = mapped_column(ARRAY(Integer), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    last_feed_file: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def to_domain(self) -> Product:
        """Convierte el modelo ORM a la entidad pura de Dominio."""
        return Product(
            product_id=self.product_id,
            title=self.title,
            price=Decimal(str(self.price)),
            store_ids=list(self.store_ids),
        )

    @classmethod
    def from_domain(cls, product: Product, feed_file: str, is_active: bool = True) -> "ProductORM":
        """Instancia un modelo ORM a partir de una entidad de Dominio."""
        return cls(
            product_id=product.product_id,
            title=product.title,
            price=product.price,
            store_ids=product.store_ids,
            is_active=is_active,
            last_feed_file=feed_file,
        )


class ListingORM(Base):
    """
    Tabla `listings`: espejo local de los anuncios publicados en Piezalia.
    """
    __tablename__ = "listings"

    listing_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    sku: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def to_domain(self) -> Listing:
        """Convierte el modelo ORM a la entidad pura de Dominio."""
        return Listing(
            listing_id=self.listing_id,
            account_id=self.account_id,
            sku=self.sku,
            title=self.title,
            price=Decimal(str(self.price)),
        )

    @classmethod
    def from_domain(cls, listing: Listing) -> "ListingORM":
        """Instancia un modelo ORM a partir de una entidad de Dominio."""
        return cls(
            listing_id=listing.listing_id,
            account_id=listing.account_id,
            sku=listing.sku,
            title=listing.title,
            price=listing.price,
        )


class SyncLogORM(Base):
    """
    Tabla `sync_log`: auditoría y trazabilidad para el equipo de soporte (Marta).
    """
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
