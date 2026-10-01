"""Safe security audit events without credentials or complete user identities."""

import logging

logger = logging.getLogger("security.audit")


def record_authentication_denial(reason_code: str) -> None:
    """Record a bounded reason code; never include token, email, key, or SQL."""
    logger.warning(
        "authentication_denied",
        extra={"event": "authentication_denied", "reason_code": reason_code},
    )
