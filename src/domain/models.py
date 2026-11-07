"""
Modelos de dominio de la aplicación.

Representan los conceptos de negocio sin depender de ninguna tecnología
concreta (ni BD, ni API, ni frameworks). Son la fuente de verdad de lo
que significa cada entidad para Portal Hero.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import List, Optional


@dataclass(frozen=True)
class Product:
    """
    Pieza del catálogo de Rovira tal como viene en el feed.

    - product_id: referencia única de la pieza en el programa de gestión de Rovira.
      Se corresponde con el campo 'sku' en la API de Piezalia.
    - store_ids: lista de cuentas en las que Jordi quiere publicar esta pieza.
    """
    product_id: str
    title: str
    price: Decimal
    store_ids: List[int]


@dataclass(frozen=True)
class Listing:
    """
    Anuncio en Piezalia tal como nos lo devuelve la API.

    - sku puede ser None si el anuncio lo publicó Jordi a mano desde el portal.
      Esos anuncios no los gestionamos nosotros y nunca se deben tocar.
    """
    listing_id: str
    account_id: int
    sku: Optional[str]
    title: str
    price: Decimal


class SyncActionType(str, Enum):
    """Tipos de operación que el sync puede ejecutar sobre un anuncio."""
    CREATE = "create"   # Publicar un anuncio nuevo
    UPDATE = "update"   # Actualizar título y/o precio de un anuncio existente
    DELETE = "delete"   # Retirar un anuncio que ya no está en el feed


@dataclass(frozen=True)
class SyncAction:
    """
    Operación pendiente de ejecutar contra la API de Piezalia.

    Representa la intención, no el resultado: es lo que el sync ha calculado
    que hay que hacer para que una cuenta quede alineada con el feed.
    """
    action_type: SyncActionType
    account_id: int
    product_id: Optional[str] = None

    # Solo para CREATE y UPDATE: datos con los que publicar/actualizar
    title: Optional[str] = None
    price: Optional[Decimal] = None

    # Solo para UPDATE y DELETE: anuncio existente que hay que modificar/retirar
    listing_id: Optional[str] = None
