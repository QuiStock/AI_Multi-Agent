from __future__ import annotations

from src.auth.account_repository import AccountRepository
from src.auth.errors import AccountLookupError, InvalidCredentialError
from src.auth.models import AuthenticatedPrincipal
from src.auth.token import JWEEmailDecoder


class AuthenticationService:
    def __init__(self, decoder: JWEEmailDecoder, accounts: AccountRepository) -> None:
        self._decoder = decoder
        self._accounts = accounts

    def authenticate(self, compact_jwe: str) -> AuthenticatedPrincipal:
        email = self._decoder.decode_email(compact_jwe)
        return self.authenticate_email(email)

    def authenticate_email(self, email: str) -> AuthenticatedPrincipal:
        try:
            account = self._accounts.find_by_email(email)
        except AccountLookupError:
            raise
        if account is None:
            raise InvalidCredentialError
        if account.role_id == 1:
            raise PermissionError
        return AuthenticatedPrincipal(email=account.email, role_id=account.role_id)
