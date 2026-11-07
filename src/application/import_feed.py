"""
Caso de uso: Importación del feed de productos a PostgreSQL.

Orquesta la lectura, validación y persistencia del catálogo exportado por Rovira:
1. Parseo y validación de campos con `FeedParser`.
2. Protección contra feeds truncados: El software antiguo de Rovira a veces exporta a medias.
   Si el feed tiene menos del umbral de seguridad (por defecto 50%) de productos
   respecto a lo que ya tenemos activo, se rechaza la importación con `TruncatedFeedError`
   para no dar de baja masivamente piezas por error.
3. Actualización atómica en base de datos:
   - Inserta o actualiza las piezas presentes y las marca activas (`is_active = TRUE`).
   - Marca como inactivas (`is_active = FALSE`) las que ya no vienen en el feed.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Dict, Union

from src.domain.exceptions import TruncatedFeedError
from src.infrastructure.csv.feed_parser import FeedParser
from src.infrastructure.database.repositories import ProductRepository

logger = logging.getLogger(__name__)


@dataclass
class ImportFeedSummary:
    """Resumen estructurado de la importación para logs y respuesta."""
    feed_file: str
    total_active: int
    deactivated: int
    parsing_errors: int
    empty_lines_skipped: int


class ImportFeedUseCase:
    """
    Caso de uso que encapsula la lógica de importación de un nuevo feed diario de Rovira.
    """

    def __init__(
        self,
        product_repo: ProductRepository,
        feed_parser: FeedParser,
        truncation_threshold: float = 0.5,
    ):
        self._product_repo = product_repo
        self._feed_parser = feed_parser
        self._truncation_threshold = truncation_threshold

    def execute(self, feed_path: Union[str, Path]) -> ImportFeedSummary:
        """
        Ejecuta el flujo completo de importación para el fichero indicado.
        """
        path = Path(feed_path)
        logger.info("Iniciando importación del feed: %s", path.name)

        # 1. Parseo del fichero CSV
        parse_result = self._feed_parser.parse_file(path)
        incoming_products = parse_result.products
        incoming_count = len(incoming_products)

        # 2. Regla de negocio crítica: Protección contra feeds truncados
        current_active_count = self._product_repo.count_active()

        if current_active_count > 0:
            ratio = incoming_count / current_active_count
            if ratio < self._truncation_threshold:
                logger.critical(
                    "ALERTA: Feed posiblemente truncado detectado. "
                    "Productos en feed: %d, catálogo activo previo: %d (ratio: %.1f%%, umbral: %.0f%%). "
                    "Importación abortada para proteger el catálogo de Piezalia.",
                    incoming_count,
                    current_active_count,
                    ratio * 100,
                    self._truncation_threshold * 100,
                )
                raise TruncatedFeedError(
                    feed_count=incoming_count,
                    current_count=current_active_count,
                    threshold=self._truncation_threshold,
                )

        # 3. Persistencia en PostgreSQL
        stats = self._product_repo.save_feed_catalog(
            products=incoming_products,
            feed_file=path.name,
        )

        summary = ImportFeedSummary(
            feed_file=path.name,
            total_active=stats["active"],
            deactivated=stats["deactivated"],
            parsing_errors=len(parse_result.errors),
            empty_lines_skipped=parse_result.empty_lines_skipped,
        )

        logger.info(
            "Importación finalizada con éxito: %d piezas activas, %d desactivadas, "
            "%d errores de línea ignorados, %d líneas vacías.",
            summary.total_active,
            summary.deactivated,
            summary.parsing_errors,
            summary.empty_lines_skipped,
        )

        return summary
