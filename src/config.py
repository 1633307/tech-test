"""
Configuración centralizada de la aplicación.

Carga las credenciales de las cuentas de Piezalia desde accounts.csv
y los parámetros de conexión desde variables de entorno (o valores por
defecto pensados para docker-compose).
"""

import csv
import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class AccountCredentials:
    """Token de autenticación de una cuenta de Piezalia."""
    account_id: int
    token: str


@dataclass(frozen=True)
class Settings:
    """Configuración global de la aplicación, inmutable una vez creada."""

    # Conexión a Postgres
    database_url: str

    # URL base de la API de Piezalia (sin / al final)
    portal_base_url: str

    # Mapa account_id -> credenciales
    accounts: Dict[int, AccountCredentials] = field(default_factory=dict)

    # Umbral de protección contra feeds truncados: porcentaje mínimo de
    # productos respecto al catálogo anterior para aceptar el feed como válido.
    # Ejemplo: 0.5 = si el feed nuevo tiene menos del 50% de productos que
    # el catálogo actual, se rechaza como posible exportación parcial.
    truncation_threshold: float = 0.5


def load_accounts(csv_path: str) -> Dict[int, AccountCredentials]:
    """
    Lee accounts.csv y devuelve un diccionario account_id -> AccountCredentials.

    El CSV tiene dos columnas: account_id, token.
    """
    accounts = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            account_id = int(row["account_id"])
            accounts[account_id] = AccountCredentials(
                account_id=account_id,
                token=row["token"].strip(),
            )
    return accounts


def load_settings() -> Settings:
    """
    Construye la configuración a partir de variables de entorno.

    Variables esperadas (con valores por defecto para docker-compose):
      - DATABASE_URL: cadena de conexión a Postgres
      - PORTAL_BASE_URL: URL base de la API de Piezalia
      - ACCOUNTS_CSV: ruta al fichero accounts.csv
      - TRUNCATION_THRESHOLD: umbral de protección (0.0 a 1.0)
    """
    accounts_csv = os.environ.get("ACCOUNTS_CSV", "accounts.csv")

    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "sqlite:///rovira.db",
        ),
        portal_base_url=os.environ.get(
            "PORTAL_BASE_URL",
            "http://localhost:8080",
        ).rstrip("/"),
        accounts=load_accounts(accounts_csv),
        truncation_threshold=float(
            os.environ.get("TRUNCATION_THRESHOLD", "0.5")
        ),
    )
