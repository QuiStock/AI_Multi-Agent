from __future__ import annotations

import docker
import psycopg
import pytest
from docker.errors import DockerException
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

from src.agents.product_workflow.tools.product_card_repository import (
    ProductCardRepository,
)

pytestmark = pytest.mark.integration


def test_product_lookup_obeys_role_store_expired_and_read_only_grants() -> None:
    try:
        docker.from_env().ping()
    except DockerException:
        pytest.skip("Docker Desktop is required for ephemeral PostgreSQL integration")

    with PostgresContainer("postgres:16-alpine") as postgres:
        admin_dsn = (
            postgres.get_connection_url()
            .replace("postgresql+psycopg2://", "postgresql://")
            .replace("postgresql+psycopg://", "postgresql://")
        )
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE ROLE product_reader LOGIN PASSWORD 'test-reader-password'"
            )
            connection.execute(
                "CREATE TABLE user_account (id INT, email TEXT, role_id INT)"
            )
            connection.execute(
                "CREATE TABLE user_store (user_id INT, store_id INT, "
                "active BOOL, unassigned_at TIMESTAMPTZ)"
            )
            connection.execute(
                "CREATE TABLE product (id INT, name TEXT, sku TEXT, category_id INT)"
            )
            connection.execute("CREATE TABLE category (id INT, name TEXT)")
            connection.execute(
                "CREATE TABLE suggestion (id INT, store_id INT, product_id INT, "
                "type TEXT, status TEXT, available_for_triage BOOL, "
                "current_batch_count INT, ml_batch_count INT, "
                "current_discount_percentage NUMERIC, "
                "ml_discount_percentage NUMERIC, reference_sale_price NUMERIC, "
                "promotional_price NUMERIC, promotion_valid_from DATE, "
                "promotion_valid_until DATE, created_at TIMESTAMPTZ)"
            )
            connection.execute(
                "CREATE TABLE suggestion_log (suggestion_id INT, event TEXT)"
            )
            connection.execute(
                "CREATE TABLE batch (product_id INT, store_id INT, "
                "expiration_date DATE, current_balance NUMERIC, active BOOL)"
            )
            connection.execute(
                "INSERT INTO user_account VALUES "
                "(1, 'employee@example.test', 3), (2, 'manager@example.test', 2)"
            )
            connection.execute(
                "INSERT INTO user_store VALUES (1, 10, TRUE, NULL), (2, 10, TRUE, NULL)"
            )
            connection.execute(
                "INSERT INTO product VALUES "
                "(100, 'Leite Integral', 'SKU-1', 5), "
                "(101, 'Leite Integral', 'SKU-2', 5), "
                "(102, 'Leite Integral', 'SKU-3', 5), "
                "(103, 'Leite Integral', 'SKU-4', 5)"
            )
            connection.execute("INSERT INTO category VALUES (5, 'Laticínios')")
            connection.execute(
                "INSERT INTO batch VALUES (103, 10, '2026-10-20', 2, TRUE)"
            )
            connection.execute(
                "INSERT INTO suggestion VALUES "
                "(200, 10, 100, 'PROMOTION', 'IN_EMPLOYEE_TRIAGE', TRUE, "
                "NULL, NULL, 15, 15, 6.50, 5.52, '2026-10-01', "
                "'2026-10-10', NOW()), "
                "(201, 10, 101, 'ORDER', 'SENT_TO_MANAGER', FALSE, 5, 5, "
                "NULL, NULL, NULL, NULL, NULL, NULL, NOW()), "
                "(202, 11, 102, 'ORDER', 'SENT_TO_MANAGER', TRUE, 5, 5, "
                "NULL, NULL, NULL, NULL, NULL, NULL, NOW()), "
                "(203, 10, 103, 'ORDER', 'IN_EMPLOYEE_TRIAGE', TRUE, 7, 7, "
                "NULL, NULL, NULL, NULL, NULL, NULL, NOW())"
            )
            connection.execute("INSERT INTO suggestion_log VALUES (200, 'EXPIRED')")
            connection.execute(
                "GRANT SELECT ON user_account, user_store, product, category, "
                "suggestion, suggestion_log, batch TO product_reader"
            )

        reader_params = conninfo_to_dict(admin_dsn)
        reader_params.update(user="product_reader", password="test-reader-password")
        pool = ConnectionPool(
            conninfo=make_conninfo(**reader_params), min_size=1, max_size=2
        )
        try:
            employee = ProductCardRepository(pool).search(
                email="employee@example.test", role_id=3, product_query="SKU-4"
            )
            employee_denied = ProductCardRepository(pool).search(
                email="employee@example.test", role_id=3, product_query="SKU-2"
            )
            manager = ProductCardRepository(pool).search(
                email="manager@example.test", role_id=2, product_query="SKU-2"
            )
            assert [card.sku for card in employee] == ["SKU-4"]
            assert employee[0].expiration_date.isoformat() == "2026-10-20"
            assert employee_denied == []
            assert [card.sku for card in manager] == ["SKU-2"]
            outside_store = ProductCardRepository(pool).search(
                email="manager@example.test", role_id=2, product_query="SKU-3"
            )
            assert outside_store == []
            expired = ProductCardRepository(pool).search(
                email="employee@example.test", role_id=3, product_query="SKU-1"
            )
            assert expired == []
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute("UPDATE suggestion SET status = 'APPROVED'")
        finally:
            pool.close()
