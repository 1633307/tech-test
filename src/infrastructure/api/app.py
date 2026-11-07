"""
API Web complementaria con FastAPI (Capa de Presentación / Infraestructura).

Permite al equipo de soporte (Marta) o integraciones externas consultar el estado
de una pieza a través de un navegador web con Swagger UI (/docs) o invocar
la sincronización vía webhook / REST.
"""

from typing import Any, Dict
from fastapi import FastAPI, HTTPException

from src.application.product_status import ProductStatusUseCase
from src.config import load_settings
from src.infrastructure.database.connection import DatabaseConnectionFactory
from src.infrastructure.database.migrations import apply_migrations
from src.infrastructure.database.repositories import (
    ListingRepository,
    ProductRepository,
    SyncLogRepository,
)

app = FastAPI(
    title="Portal Hero - Piezalia Catalog Sync API",
    description="API de consulta y sincronización de catálogo de Desguaces Rovira con Piezalia.",
    version="1.0.0",
)


@app.get("/health", tags=["Salud"])
def health_check() -> Dict[str, str]:
    """Endpoint de comprobación de salud del servicio."""
    return {"status": "ok"}


@app.get("/status/{product_id}", tags=["Soporte"])
def get_product_status(product_id: str) -> Dict[str, Any]:
    """
    Endpoint para que Marta o soporte consulte el estado exacto de una pieza
    en el catálogo y sus anuncios en Piezalia.
    """
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

    data = use_case.get_status_data(product_id)
    if not data.get("product_found"):
        raise HTTPException(status_code=404, detail=f"Pieza {product_id} no encontrada en el catálogo")

    return data
