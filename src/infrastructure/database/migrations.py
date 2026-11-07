"""
Migraciones y definición del esquema relacional en PostgreSQL.

Crea las tablas necesarias de manera idempotente para almacenar:
1. `products`: El catálogo extraído de los feeds de Rovira.
2. `listings`: Espejo local de los anuncios publicados en Piezalia.
3. `sync_log`: Historial y auditoría de sincronización para soporte técnico (Marta).
"""

import logging
from src.infrastructure.database.connection import DatabaseConnectionFactory

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- 1. Catálogo de productos importados del feed de Rovira.
-- Guardamos tanto los productos activos en el último feed como el histórico de su estado.
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    price NUMERIC(7, 2) NOT NULL,
    store_ids INTEGER[] NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_feed_file TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índice para acelerar la búsqueda de productos activos durante la sincronización
CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active);

-- 2. Espejo local de anuncios en Piezalia por cuenta.
-- Permite comparar el estado real del portal con el feed sin depender exclusivamente
-- de peticiones lentas o limitadas por rate-limiting a Piezalia.
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    sku TEXT,                       -- NULL si Jordi lo publicó manualmente desde Piezalia
    title TEXT NOT NULL,
    price NUMERIC(7, 2) NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para búsquedas rápidas por cuenta y por SKU
CREATE INDEX IF NOT EXISTS idx_listings_account_sku ON listings(account_id, sku);
CREATE INDEX IF NOT EXISTS idx_listings_sku ON listings(sku);

-- 3. Registro de auditoría y sincronizaciones.
-- Crucial para que Marta pueda explicar inmediatamente a Jordi qué ocurrió con una pieza
-- (ej. 'falló token expirado', '429 rate limit', '503 reintentado', etc.)
CREATE TABLE IF NOT EXISTS sync_log (
    id SERIAL PRIMARY KEY,
    product_id TEXT,
    account_id INTEGER NOT NULL,
    action TEXT NOT NULL,           -- 'create', 'update', 'delete', 'error', 'skip'
    status TEXT NOT NULL,           -- 'success', 'failed', 'skipped'
    detail TEXT,                    -- Descripción del resultado o motivo del error
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sync_log_product ON sync_log(product_id, account_id);
"""


def apply_migrations(db_factory: DatabaseConnectionFactory) -> None:
    """
    Ejecuta el script DDL de creación de tablas e índices si no existen.
    """
    logger.info("Aplicando migraciones en la base de datos...")
    with db_factory.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)
    logger.info("Migraciones aplicadas correctamente.")
