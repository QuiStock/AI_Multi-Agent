from __future__ import annotations

import docker
import psycopg
import pytest
from docker.errors import DockerException
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

from src.auth.account_repository import PostgresAccountRepository

pytestmark = pytest.mark.integration


def test_read_only_account_lookup_against_postgres_container() -> None:
    try:
        docker.from_env().ping()
    except DockerException:
        pytest.skip("Docker Desktop is required for PostgreSQL integration")
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
                "CREATE TABLE role (id BIGINT PRIMARY KEY, code TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE user_account "
                "(id BIGINT PRIMARY KEY, email TEXT, role_id INTEGER, status TEXT)"
            )
            connection.execute(
                "CREATE TABLE store (id BIGINT PRIMARY KEY, status TEXT)"
            )
            connection.execute(
                "CREATE TABLE user_store "
                "(user_id BIGINT, store_id BIGINT, active BOOLEAN, "
                "unassigned_at TIMESTAMPTZ)"
            )
            connection.execute("INSERT INTO role VALUES (91, 'MANAGER')")
            connection.execute(
                "INSERT INTO user_account VALUES "
                "(42, 'reader@example.test', 91, 'ACTIVE')"
            )
            connection.execute(
                "INSERT INTO store VALUES (4, 'ACTIVE'), (9, 'INACTIVE')"
            )
            connection.execute(
                "INSERT INTO user_store VALUES (42, 4, TRUE, NULL), (42, 9, TRUE, NULL)"
            )
            connection.execute(
                "GRANT SELECT ON role, user_account, store, user_store "
                "TO ai_auth_reader"
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
            account = PostgresAccountRepository(pool).find_by_id(42)
            assert account is not None
            assert account.user_id == 42
            assert account.email == "reader@example.test"
            assert account.role_code == "MANAGER"
            assert account.store_ids == (4,)

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute(
                        "UPDATE user_account SET role_id = 0 WHERE id = 42"
                    )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute("CREATE TABLE forbidden_ddl (id INTEGER)")
        finally:
            pool.close()
