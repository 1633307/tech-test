"""
Gestión de conexiones y sesiones de base de datos con SQLAlchemy 2.0.

Soporta de forma transparente:
- PostgreSQL (producción / docker-compose).
- SQLite (desarrollo local sin Docker para pruebas inmedias).
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
        url = database_url

        engine_kwargs = {}
        if url.startswith("sqlite"):
            # Para SQLite permitimos uso multihilo seguro
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        else:
            # Compatibilidad con psycopg2 en PostgreSQL
            if url.startswith("postgresql://") and not url.startswith("postgresql+psycopg2://"):
                url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
            engine_kwargs["pool_pre_ping"] = True
            engine_kwargs["pool_size"] = 5
            engine_kwargs["max_overflow"] = 10

        self._database_url = url
        self._engine: Engine = create_engine(self._database_url, **engine_kwargs)
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
