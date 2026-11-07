"""
Gestión de conexiones a la base de datos PostgreSQL.

Proporciona utilidades para obtener conexiones y cursores dentro de un
bloque de contexto (contextmanager), asegurando el commit automático en
éxito o el rollback ante cualquier fallo, además de devolver la conexión
al pool o cerrarla correctamente.
"""

from contextlib import contextmanager
import logging
from typing import Generator
import psycopg2
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class DatabaseConnectionFactory:
    """
    Fábrica encargada de instanciar y gestionar conexiones directas con PostgreSQL.
    """

    def __init__(self, database_url: str):
        self._database_url = database_url

    def get_raw_connection(self) -> PgConnection:
        """Crea y devuelve una conexión nueva a PostgreSQL."""
        return psycopg2.connect(self._database_url)

    @contextmanager
    def get_connection(self) -> Generator[PgConnection, None, None]:
        """
        Context manager para una conexión gestionada.
        Realiza commit si todo va bien, rollback si ocurre una excepción,
        y asegura el cierre de la conexión al finalizar.
        """
        conn = self.get_raw_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Transacción abortada con rollback por error: %s", e)
            raise
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self, cursor_factory=RealDictCursor):
        """
        Context manager que proporciona directamente un cursor (por defecto RealDictCursor)
        dentro de una transacción segura.
        """
        with self.get_connection() as conn:
            with conn.cursor(cursor_factory=cursor_factory) as cursor:
                yield cursor
