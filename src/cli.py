"""
Punto de entrada de línea de comandos (CLI) para Portal Hero.

Expone los tres comandos requeridos para la gestión del catálogo de Desguaces Rovira:
  - `import <feed_path>`: Lee el feed CSV y actualiza el catálogo en PostgreSQL.
  - `sync`: Sincroniza el catálogo de Rovira con las 4 cuentas de Piezalia.
  - `status <product_id>`: Consulta rápida para el equipo de soporte (Marta).

Diseñado para ejecutarse desatendido en un cron (con códigos de salida adecuados y logs).
"""

import argparse
import logging
import sys
from typing import List, Optional

# Configuración de logging para ejecución desatendida
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("portal_hero")


def build_parser() -> argparse.ArgumentParser:
    """Construye el analizador de argumentos y subcomandos."""
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Portal Hero CLI - Sincronizador de catálogos para Piezalia (Desguaces Rovira)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Comando a ejecutar")

    # 1. Subcomando: import <feed>
    import_parser = subparsers.add_parser(
        "import",
        help="Lee el fichero CSV de feed y almacena el catálogo actualizado en PostgreSQL",
    )
    import_parser.add_argument(
        "feed_path",
        type=str,
        help="Ruta al fichero CSV del feed (ej. data/feed_dia1.csv)",
    )

    # 2. Subcomando: sync
    subparsers.add_parser(
        "sync",
        help="Sincroniza las cuentas de Piezalia para reflejar exactamente el catálogo activo",
    )

    # 3. Subcomando: status <product_id>
    status_parser = subparsers.add_parser(
        "status",
        help="Muestra el estado detallado de una pieza y sus anuncios para soporte (Marta)",
    )
    status_parser.add_argument(
        "product_id",
        type=str,
        help="Identificador de la pieza / SKU de Rovira (ej. 8090)",
    )

    return parser


def handle_import(feed_path: str) -> int:
    """Manejador del comando `import`."""
    try:
        from src.application.import_feed import ImportFeedUseCase
        from src.config import load_settings
        from src.infrastructure.csv.feed_parser import FeedParser
        from src.infrastructure.database.connection import DatabaseConnectionFactory
        from src.infrastructure.database.migrations import apply_migrations
        from src.infrastructure.database.repositories import ProductRepository

        settings = load_settings()
        db_factory = DatabaseConnectionFactory(settings.database_url)
        apply_migrations(db_factory)

        repo = ProductRepository(db_factory)
        parser = FeedParser()
        use_case = ImportFeedUseCase(
            product_repo=repo,
            feed_parser=parser,
            truncation_threshold=settings.truncation_threshold,
        )

        use_case.execute(feed_path)
        return 0
    except Exception as exc:
        logger.error("Error al importar el feed: %s", exc)
        return 1


def handle_sync() -> int:
    """Manejador del comando `sync`."""
    try:
        from src.application.sync_catalog import SyncCatalogUseCase
        from src.config import load_settings
        from src.infrastructure.database.connection import DatabaseConnectionFactory
        from src.infrastructure.database.migrations import apply_migrations
        from src.infrastructure.database.repositories import (
            ListingRepository,
            ProductRepository,
            SyncLogRepository,
        )
        from src.infrastructure.portal.client import PiezaliaClient

        settings = load_settings()
        db_factory = DatabaseConnectionFactory(settings.database_url)
        apply_migrations(db_factory)

        product_repo = ProductRepository(db_factory)
        listing_repo = ListingRepository(db_factory)
        sync_log_repo = SyncLogRepository(db_factory)
        portal_client = PiezaliaClient(
            base_url=settings.portal_base_url,
            accounts=settings.accounts,
        )

        use_case = SyncCatalogUseCase(
            product_repo=product_repo,
            listing_repo=listing_repo,
            sync_log_repo=sync_log_repo,
            portal_client=portal_client,
            accounts=settings.accounts,
        )

        use_case.execute()
        return 0
    except Exception as exc:
        logger.error("Error al ejecutar sincronización: %s", exc)
        return 1


def handle_status(product_id: str) -> int:
    """Manejador del comando `status`."""
    try:
        from src.application.product_status import ProductStatusUseCase
        from src.config import load_settings
        from src.infrastructure.database.connection import DatabaseConnectionFactory
        from src.infrastructure.database.migrations import apply_migrations
        from src.infrastructure.database.repositories import (
            ListingRepository,
            ProductRepository,
            SyncLogRepository,
        )

        settings = load_settings()
        db_factory = DatabaseConnectionFactory(settings.database_url)
        apply_migrations(db_factory)

        product_repo = ProductRepository(db_factory)
        listing_repo = ListingRepository(db_factory)
        sync_log_repo = SyncLogRepository(db_factory)

        use_case = ProductStatusUseCase(
            product_repo=product_repo,
            listing_repo=listing_repo,
            sync_log_repo=sync_log_repo,
        )

        report = use_case.execute(product_id)
        print(report)
        return 0
    except Exception as exc:
        logger.error("Error al consultar el estado: %s", exc)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Punto de entrada principal."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "import":
        return handle_import(args.feed_path)
    elif args.command == "sync":
        return handle_sync()
    elif args.command == "status":
        return handle_status(args.product_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
