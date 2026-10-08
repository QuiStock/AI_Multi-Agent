from __future__ import annotations

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

from src.auth.account_repository import PostgresAccountRepository

pytestmark = pytest.mark.integration


def test_read_only_account_lookup_against_postgres_container() -> None:
    with PostgresContainer("postgres:16-alpine") as postgres:
        admin_dsn = (
            postgres.get_connection_url()
            .replace("postgresql+psycopg2://", "postgresql://")
            .replace("postgresql+psycopg://", "postgresql://")
        )
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE ROLE ai_auth_reader LOGIN PASSWORD 'test-only-password'"
            )
            connection.execute(
                "CREATE TABLE user_account "
                "(email TEXT PRIMARY KEY, role_id INTEGER NOT NULL)"
            )
            connection.execute(
                "INSERT INTO user_account(email, role_id) "
                "VALUES ('reader@example.test', 2)"
            )
            connection.execute(
                "GRANT SELECT (email, role_id) ON user_account TO ai_auth_reader"
            )

        connection_params = conninfo_to_dict(admin_dsn)
        connection_params["user"] = "ai_auth_reader"
        connection_params["password"] = "test-only-password"
        reader_dsn = make_conninfo(**connection_params)
        pool = ConnectionPool(
            conninfo=reader_dsn,
            min_size=1,
            max_size=2,
            timeout=3,
        )
        try:
            account = PostgresAccountRepository(pool).find_by_email(
                "reader@example.test"
            )
            assert account is not None
            assert account.email == "reader@example.test"
            assert account.role_id == 2

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute(
                        "UPDATE user_account SET role_id = 1 "
                        "WHERE email = 'reader@example.test'"
                    )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute("CREATE TABLE forbidden_ddl (id INTEGER)")
        finally:
            pool.close()
