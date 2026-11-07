"""
Gestión de conexiones y sesiones de base de datos con SQLAlchemy 2.0.

Proporciona un SessionFactory con context manager (`get_session()`) que garantiza:
- Commit automático si el bloque de código se completa sin excepciones.
- Rollback automático ante cualquier error.
- Cierre y devolución adecuada de conexiones al pool.
"""

from contextlib import contextmanager
import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


class DatabaseConnectionFactory:
    """
    Fábrica de sesiones y motor de base de datos para SQLAlchemy 2.0.
    """

    def __init__(self, database_url: str):
        # Aseguramos compatibilidad con el driver de psycopg2 en SQLAlchemy
        url = database_url
        if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

        self._database_url = url
        self._engine: Engine = create_engine(
            self._database_url,
            pool_pre_ping=True,  # Verifica conexiones activas antes de usarlas
            pool_size=5,
            max_overflow=10,
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> Engine:
        """Acceso al motor SQLAlchemy subyacente (por ejemplo para migraciones DDL)."""
        return self._engine

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Context manager que entrega una sesión ORM gestionada:
        hace commit automático al salir sin errores y rollback en caso de fallo.
        """
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Error en sesión de base de datos, transacción abortada con rollback: %s", e)
            raise
        finally:
            session.close()
