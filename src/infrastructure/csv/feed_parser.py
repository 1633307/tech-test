"""
Parser robusto para los ficheros de feed CSV exportados por Desguaces Rovira.

Gestiona las particularidades y anomalías detectadas en los feeds reales:
1. Líneas vacías intercaladas producidas por el ERP antiguo de Rovira.
2. Espacios en blanco accidentales en store_id (ej. ' 2 | 3 ').
3. Formato de precios: exige decimal con punto (> 0 y <= 99999.99 con máx. 2 decimales).
   Si viene con formato español ('443,90') o inválido, se registra como error de línea
   sin abortar el procesamiento del resto del feed.
4. Longitud de títulos: Piezalia rechaza títulos con más de 80 caracteres (422 validation).
   Los seed listings del portal evidencian que el sistema trunca a 80 caracteres.
   El parser recorta títulos a 80 caracteres para evitar rechazos en Piezalia.
"""

import csv
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union

from src.domain.exceptions import FeedParsingError
from src.domain.models import Product

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 80
MAX_PRICE = Decimal("99999.99")
CENT = Decimal("0.01")


@dataclass
class FeedParseResult:
    """Resultado del procesamiento de un feed CSV."""
    products: List[Product] = field(default_factory=list)
    errors: List[FeedParsingError] = field(default_factory=list)
    empty_lines_skipped: int = 0
    total_lines_read: int = 0


class FeedParser:
    """
    Parser del feed CSV con validación estricta por campo y tolerancia a fallos por línea.
    """

    def parse_file(self, file_path: Union[str, Path]) -> FeedParseResult:
        """
        Lee y procesa un fichero CSV del catálogo de Rovira.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"No se encontró el fichero de feed en: {path}")

        result = FeedParseResult()

        with open(path, mode="r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)

            # 1. Leer encabezado
            try:
                header = next(reader)
            except StopIteration:
                logger.warning("El fichero de feed está totalmente vacío: %s", path)
                return result

            result.total_lines_read += 1
            expected_header = ["product_id", "title", "price", "store_id"]
            cleaned_header = [h.strip() for h in header]

            if cleaned_header != expected_header:
                logger.warning(
                    "Encabezado inesperado en %s: %s (se esperaba %s)",
                    path,
                    cleaned_header,
                    expected_header,
                )

            # 2. Procesar línea por línea
            for line_idx, row in enumerate(reader, start=2):
                result.total_lines_read += 1

                # Trampa detectada en feed_dia2: líneas completamente vacías
                if not row or not any(field.strip() for field in row):
                    result.empty_lines_skipped += 1
                    continue

                if len(row) < 4:
                    err = FeedParsingError(
                        line_number=line_idx,
                        reason=f"Faltan columnas (se encontraron {len(row)}, requeridas 4)",
                        raw_line=",".join(row),
                    )
                    result.errors.append(err)
                    logger.warning(str(err))
                    continue

                raw_product_id, raw_title, raw_price, raw_store_id = (
                    row[0].strip(),
                    row[1].strip(),
                    row[2].strip(),
                    row[3].strip(),
                )

                # Validación de product_id (SKU en Piezalia)
                if not raw_product_id:
                    err = FeedParsingError(
                        line_number=line_idx,
                        reason="product_id está vacío",
                        raw_line=",".join(row),
                    )
                    result.errors.append(err)
                    continue

                # Validación y truncado de título (máximo 80 caracteres requerido por Piezalia)
                if not raw_title:
                    err = FeedParsingError(
                        line_number=line_idx,
                        reason="El título está vacío",
                        raw_line=",".join(row),
                    )
                    result.errors.append(err)
                    continue

                clean_title = raw_title[:MAX_TITLE_LENGTH].strip()

                # Validación de precio (debe ser decimal con punto, máx 2 decimales, > 0)
                price_val, price_err = self._parse_price(raw_price, line_idx, row)
                if price_err:
                    result.errors.append(price_err)
                    logger.warning(str(price_err))
                    continue

                # Validación de store_ids (ej. ' 2 | 3 ' -> [2, 3])
                store_ids, store_err = self._parse_store_ids(raw_store_id, line_idx, row)
                if store_err:
                    result.errors.append(store_err)
                    logger.warning(str(store_err))
                    continue

                result.products.append(
                    Product(
                        product_id=raw_product_id,
                        title=clean_title,
                        price=price_val,
                        store_ids=store_ids,
                    )
                )

        logger.info(
            "Feed %s procesado: %d productos válidos, %d errores, %d líneas vacías ignoradas.",
            path.name,
            len(result.products),
            len(result.errors),
            result.empty_lines_skipped,
        )
        return result

    def _parse_price(
        self, raw_price: str, line_number: int, row: List[str]
    ) -> Tuple[Optional[Decimal], Optional[FeedParsingError]]:
        """
        Valida que el precio cumpla los requisitos de Piezalia:
        - Debe usar punto como separador decimal.
        - Mayor que 0 y menor o igual a 99999.99.
        - Máximo dos decimales.
        """
        # Si contiene coma, es formato inválido según la especificación del feed
        if "," in raw_price:
            return None, FeedParsingError(
                line_number=line_number,
                reason=f"Precio '{raw_price}' usa coma en lugar de punto decimal",
                raw_line=",".join(row),
            )

        try:
            price = Decimal(raw_price)
        except InvalidOperation:
            return None, FeedParsingError(
                line_number=line_number,
                reason=f"Precio '{raw_price}' no es un número válido",
                raw_line=",".join(row),
            )

        if not price.is_finite() or price <= Decimal("0.00") or price > MAX_PRICE:
            return None, FeedParsingError(
                line_number=line_number,
                reason=f"Precio {price} fuera de rango permitido (0 < precio <= {MAX_PRICE})",
                raw_line=",".join(row),
            )

        quantized = price.quantize(CENT)
        if price != quantized:
            return None, FeedParsingError(
                line_number=line_number,
                reason=f"Precio '{raw_price}' tiene más de 2 decimales",
                raw_line=",".join(row),
            )

        return quantized, None

    def _parse_store_ids(
        self, raw_store_id: str, line_number: int, row: List[str]
    ) -> Tuple[List[int], Optional[FeedParsingError]]:
        """
        Parsea y limpia la lista de cuentas separadas por barra vertical '|'.
        Limpia espacios en blanco alrededor de cada cuenta.
        """
        if not raw_store_id:
            return [], FeedParsingError(
                line_number=line_number,
                reason="store_id está vacío (la pieza debe asignarse al menos a una cuenta)",
                raw_line=",".join(row),
            )

        tokens = [t.strip() for t in raw_store_id.split("|") if t.strip()]
        if not tokens:
            return [], FeedParsingError(
                line_number=line_number,
                reason=f"store_id '{raw_store_id}' no contiene cuentas válidas",
                raw_line=",".join(row),
            )

        store_ids = []
        for token in tokens:
            try:
                store_id = int(token)
                if store_id not in store_ids:
                    store_ids.append(store_id)
            except ValueError:
                return [], FeedParsingError(
                    line_number=line_number,
                    reason=f"Cuenta '{token}' en store_id no es un entero válido",
                    raw_line=",".join(row),
                )

        return sorted(store_ids), None
