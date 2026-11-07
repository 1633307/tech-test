"""
Excepciones de dominio.

Cada excepción representa un problema de negocio, no un fallo técnico.
Las capas superiores (CLI, casos de uso) las capturan para decidir cómo
informar al usuario o al log.
"""


class TruncatedFeedError(Exception):
    """
    El feed tiene muchos menos productos de los esperados.

    El programa de gestión de Rovira es viejo y a veces exporta el CSV a medias.
    Cuando detectamos esto, rechazamos el feed entero para evitar borrar
    anuncios válidos de Piezalia, lo que causaría pérdida de posicionamiento
    y posibles reclamaciones.
    """
    def __init__(self, feed_count: int, current_count: int, threshold: float):
        self.feed_count = feed_count
        self.current_count = current_count
        self.threshold = threshold
        ratio = feed_count / current_count if current_count > 0 else 0
        super().__init__(
            f"Feed posiblemente truncado: {feed_count} productos "
            f"(catálogo actual: {current_count}, ratio: {ratio:.1%}, "
            f"umbral: {threshold:.0%}). "
            f"Se rechaza el feed por seguridad."
        )


class PortalApiError(Exception):
    """
    Error al comunicarse con la API de Piezalia.

    Envuelve los errores de la API con código y detalle para que los
    casos de uso puedan decidir si reintentar, saltar o abortar.
    """
    def __init__(self, status_code: int, error_code: str, detail: str):
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail
        super().__init__(
            f"Piezalia respondió {status_code} ({error_code}): {detail}"
        )


class TokenExpiredError(PortalApiError):
    """
    El token de una cuenta ha caducado.

    No se puede resolver reintentando: Jordi tiene que renovar el token
    en el portal de Piezalia. Cuando ocurre, se salta esa cuenta y se
    continúa con las demás.
    """
    def __init__(self, account_id: int, detail: str = ""):
        self.account_id = account_id
        super().__init__(
            status_code=401,
            error_code="token_expired",
            detail=detail or f"Token expirado para la cuenta {account_id}",
        )


class FeedParsingError(Exception):
    """
    Error al parsear una línea del feed CSV.

    No aborta la importación: se registra el error y se continúa con las
    demás líneas. El log permite investigar después qué líneas fallaron.
    """
    def __init__(self, line_number: int, reason: str, raw_line: str = ""):
        self.line_number = line_number
        self.reason = reason
        self.raw_line = raw_line
        super().__init__(
            f"Error en línea {line_number} del feed: {reason}"
        )
