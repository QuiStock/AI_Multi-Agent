from __future__ import annotations

from src.auth.account_repository import AccountRepository
from src.auth.errors import InvalidCredentialError
from src.auth.models import AuthenticatedPrincipal, VerifiedToken
from src.auth.permissions import CONVERSATION_ROLE_CODES


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
        if account.role_code not in CONVERSATION_ROLE_CODES or not account.store_ids:
            raise PermissionError
        return AuthenticatedPrincipal(
            user_id=account.user_id,
            email=account.email,
            role_code=account.role_code,
            store_ids=account.store_ids,
        )
