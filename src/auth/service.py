from __future__ import annotations

from src.auth.account_repository import AccountRepository
from src.auth.errors import InvalidCredentialError
from src.auth.models import AuthenticatedPrincipal, VerifiedToken


class AuthenticationService:
    def __init__(self, accounts: AccountRepository) -> None:
        self._accounts = accounts

    def authenticate(self, identity: VerifiedToken) -> AuthenticatedPrincipal:
        account = self._accounts.find_by_id(identity.user_id)
        if (
            account is None
            or account.status != "ACTIVE"
            or account.email != identity.email
        ):
            raise InvalidCredentialError
        if account.role_id not in (2, 3) or not account.store_ids:
            raise PermissionError
        return AuthenticatedPrincipal(
            user_id=account.user_id,
            email=account.email,
            role_id=account.role_id,
            store_ids=account.store_ids,
        )
