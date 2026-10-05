from __future__ import annotations

from src.auth.account_repository import AccountRepository
from src.auth.errors import InvalidCredentialError
from src.auth.models import AuthenticatedPrincipal
from src.auth.token import JWTEmailDecoder


class AuthenticationService:
    def __init__(self, decoder: JWTEmailDecoder, accounts: AccountRepository) -> None:
        self._decoder = decoder
        self._accounts = accounts

    def authenticate(self, compact_jwt: str) -> AuthenticatedPrincipal:
        email = self._decoder.decode_email(compact_jwt)
        account = self._accounts.find_by_email(email)
        if account is None:
            raise InvalidCredentialError
        if account.role_id == 1:
            raise PermissionError
        return AuthenticatedPrincipal(email=account.email, role_id=account.role_id)
