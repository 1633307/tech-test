"""
Migraciones y creación del esquema relacional en PostgreSQL mediante SQLAlchemy 2.0.

Crea las tablas `products`, `listings` y `sync_log` de forma idempotente a partir
de los modelos declarativos de SQLAlchemy (`Base.metadata.create_all`).
"""

import logging
from src.infrastructure.database.connection import DatabaseConnectionFactory
from src.infrastructure.database.orm_models import Base

logger = logging.getLogger(__name__)


def apply_migrations(db_factory: DatabaseConnectionFactory) -> None:
    """
    Crea las tablas e índices definidos en los modelos ORM si no existen.
    """
    logger.info("Aplicando esquema de tablas mediante SQLAlchemy 2.0 DDL...")
    Base.metadata.create_all(bind=db_factory.engine)
    logger.info("Esquema relacional verificado y listo.")
