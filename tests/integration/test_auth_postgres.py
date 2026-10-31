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
            connection.execute("CREATE TYPE user_status AS ENUM ('ACTIVE', 'INACTIVE')")
            connection.execute(
                "CREATE TYPE store_status AS ENUM ('ACTIVE', 'INACTIVE')"
            )
            connection.execute(
                """
                CREATE TABLE role (
                    id BIGINT PRIMARY KEY,
                    code VARCHAR(50) NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE user_account (
                    id BIGINT PRIMARY KEY,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    role_id BIGINT NOT NULL,
                    status user_status NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE store (
                    id BIGINT PRIMARY KEY,
                    status store_status NOT NULL,
                    region_id BIGINT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE user_store (
                    user_id BIGINT NOT NULL,
                    store_id BIGINT NOT NULL,
                    active BOOLEAN NOT NULL,
                    unassigned_at TIMESTAMPTZ
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE region_manager_assignment (
                    region_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    active BOOLEAN NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO role(id, code)
                VALUES (20, 'MANAGER'), (21, 'EMPLOYEE'), (22, 'REGIONAL_MANAGER')
                """
            )
            connection.execute(
                """
                INSERT INTO store(id, status, region_id)
                VALUES
                    (30, 'ACTIVE', NULL),
                    (31, 'INACTIVE', NULL),
                    (32, 'ACTIVE', NULL),
                    (40, 'ACTIVE', 9)
                """
            )
            connection.execute(
                """
                INSERT INTO user_account(id, email, role_id, status)
                VALUES
                    (7, 'reader@example.test', 20, 'ACTIVE'),
                    (8, 'employee@example.test', 21, 'ACTIVE'),
                    (9, 'regional@example.test', 22, 'ACTIVE'),
                    (10, 'inactive@example.test', 20, 'INACTIVE'),
                    (11, 'twostores@example.test', 20, 'ACTIVE'),
                    (12, 'closedstore@example.test', 21, 'ACTIVE')
                """
            )
            connection.execute(
                """
                INSERT INTO user_store(user_id, store_id, active, unassigned_at)
                VALUES
                    (7, 30, TRUE, NULL),
                    (7, 32, FALSE, CURRENT_TIMESTAMP),
                    (8, 32, TRUE, NULL),
                    (11, 30, TRUE, NULL),
                    (11, 32, TRUE, NULL),
                    (12, 31, TRUE, NULL)
                """
            )
            connection.execute(
                """
                INSERT INTO region_manager_assignment(region_id, user_id, active)
                VALUES (9, 9, TRUE)
                """
            )
            connection.execute(
                "GRANT SELECT (id, email, role_id, status) "
                "ON user_account TO ai_auth_reader"
            )
            connection.execute("GRANT SELECT (id, code) ON role TO ai_auth_reader")
            connection.execute(
                "GRANT SELECT (user_id, store_id, active, unassigned_at) "
                "ON user_store TO ai_auth_reader"
            )
            connection.execute("GRANT SELECT (id, status) ON store TO ai_auth_reader")

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
            repository = PostgresAccountRepository(pool)
            manager = repository.find_by_email("reader@example.test")
            assert manager is not None
            assert manager.user_id == 7
            assert manager.email == "reader@example.test"
            assert manager.role_code == "MANAGER"
            assert manager.store_ids == (30,)

            employee = repository.find_by_email("employee@example.test")
            assert employee is not None
            assert employee.role_code == "EMPLOYEE"
            assert employee.store_ids == (32,)

            regional = repository.find_by_email("regional@example.test")
            assert regional is not None
            assert regional.role_code == "REGIONAL_MANAGER"
            assert regional.store_ids == ()

            closed_store = repository.find_by_email("closedstore@example.test")
            assert closed_store is not None
            assert closed_store.store_ids == ()

            several = repository.find_by_email("twostores@example.test")
            assert several is not None
            assert set(several.store_ids) == {30, 32}

            assert repository.find_by_email("inactive@example.test") is None
            assert repository.find_by_email("missing@example.test") is None

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute(
                        "UPDATE user_account SET status = 'INACTIVE' "
                        "WHERE email = 'reader@example.test'"
                    )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute("CREATE TABLE forbidden_ddl (id INTEGER)")
        finally:
            pool.close()
