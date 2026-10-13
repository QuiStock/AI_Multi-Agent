class InvalidCredentialError(ValueError):
    """The bearer token cannot establish a valid local identity."""


class AuthenticationConfigurationError(RuntimeError):
    """The trusted JWT issuer or JWKS configuration is missing."""


class AuthenticationDependencyError(RuntimeError):
    """The trusted JWKS endpoint is unavailable or unusable."""


class AccountLookupError(RuntimeError):
    """The PostgreSQL account lookup could not be completed."""
