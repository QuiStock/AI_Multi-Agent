class InvalidCredentialError(ValueError):
    """The bearer token cannot establish an email identity."""


class AuthenticationConfigurationError(RuntimeError):
    """The JWE key configuration is missing or invalid."""


class AccountLookupError(RuntimeError):
    """The PostgreSQL account lookup could not be completed."""
