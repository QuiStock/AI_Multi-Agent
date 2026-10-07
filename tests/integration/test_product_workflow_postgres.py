from __future__ import annotations

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

from src.agents.product_workflow.models import ProductWorkflowContext
from src.agents.product_workflow.repository import (
    PostgresProductWorkflowRepository,
)

pytestmark = pytest.mark.integration


def test_product_workflow_reads_postgres_with_select_only_grants() -> None:
    with PostgresContainer("postgres:16-alpine") as postgres:
        admin_dsn = (
            postgres.get_connection_url()
            .replace("postgresql+psycopg2://", "postgresql://")
            .replace("postgresql+psycopg://", "postgresql://")
        )
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE ROLE ai_product_reader LOGIN PASSWORD 'test-only-password'"
            )
            connection.execute(
                "CREATE TYPE suggestion_type AS ENUM ('ORDER', 'PROMOTION', 'MONITOR')"
            )
            connection.execute(
                "CREATE TYPE suggestion_origin AS ENUM ('ML', 'EMPLOYEE', 'MANAGER')"
            )
            connection.execute(
                "CREATE TYPE suggestion_status AS ENUM "
                "('GENERATED', 'IN_EMPLOYEE_TRIAGE', 'SENT_TO_MANAGER', "
                "'APPROVED', 'REJECTED')"
            )
            connection.execute(
                "CREATE TYPE suggestion_log_event AS ENUM "
                "('GENERATED', 'EDITED', 'FORWARDED', 'APPROVED', "
                "'REJECTED', 'EXPIRED')"
            )
            connection.execute(
                """
                CREATE TABLE user_account (
                    id BIGINT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    role_id BIGINT NOT NULL,
                    status TEXT NOT NULL
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
                CREATE TABLE store (
                    id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE category (
                    id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    active BOOLEAN NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE product (
                    id BIGINT PRIMARY KEY,
                    category_id BIGINT,
                    sku TEXT NOT NULL,
                    name TEXT NOT NULL,
                    active BOOLEAN NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE suggestion_log (
                    id BIGINT PRIMARY KEY,
                    suggestion_id BIGINT NOT NULL,
                    event suggestion_log_event NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE suggestion (
                    id BIGINT PRIMARY KEY,
                    product_analysis_id BIGINT,
                    store_id BIGINT NOT NULL,
                    product_id BIGINT NOT NULL,
                    type suggestion_type NOT NULL,
                    origin suggestion_origin NOT NULL,
                    status suggestion_status NOT NULL,
                    ml_batch_count INTEGER,
                    current_batch_count INTEGER,
                    ml_discount_percentage NUMERIC(5, 2),
                    current_discount_percentage NUMERIC(5, 2),
                    promotion_valid_from DATE,
                    promotion_valid_until DATE,
                    reference_sale_price NUMERIC(12, 2),
                    promotional_price NUMERIC(12, 2),
                    available_for_triage BOOLEAN NOT NULL,
                    created_by_id BIGINT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE suggestion_triage (
                    id BIGINT PRIMARY KEY,
                    suggestion_id BIGINT UNIQUE NOT NULL,
                    employee_id BIGINT,
                    last_action TEXT NOT NULL,
                    forwarded_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE batch (
                    id BIGINT PRIMARY KEY,
                    product_id BIGINT NOT NULL,
                    store_id BIGINT NOT NULL,
                    expiration_date DATE NOT NULL,
                    current_balance NUMERIC(14, 3) NOT NULL,
                    active BOOLEAN NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO user_account(id, email, name, role_id, status)
                VALUES (7, 'reader@example.test', 'Leitor Teste', 2, 'ACTIVE'),
                       (8, 'employee@example.test', 'Funcionária Teste', 3, 'ACTIVE')
                """
            )
            connection.execute(
                """
                INSERT INTO user_store(user_id, store_id, active)
                VALUES (7, 30, TRUE), (8, 30, TRUE)
                """
            )
            connection.execute(
                "INSERT INTO store(id, name, status) "
                "VALUES (30, 'Loja Teste', 'ACTIVE')"
            )
            connection.execute(
                "INSERT INTO category(id, name, active) VALUES (50, 'Laticínios', TRUE)"
            )
            connection.execute(
                """
                INSERT INTO product(id, category_id, sku, name, active)
                VALUES (40, 50, 'SKU-40', 'Leite Integral UHT 1L', TRUE)
                """
            )
            connection.execute(
                """
                INSERT INTO suggestion(
                    id, product_analysis_id, store_id, product_id, type, origin,
                    status, ml_batch_count, current_batch_count,
                    ml_discount_percentage, current_discount_percentage,
                    promotion_valid_from, promotion_valid_until,
                    reference_sale_price, promotional_price, available_for_triage,
                    created_by_id, created_at, updated_at
                ) VALUES
                    (10, 100, 30, 40, 'ORDER', 'ML', 'SENT_TO_MANAGER', 2, 2,
                     NULL, NULL, NULL, NULL, 10.00, NULL, TRUE, NULL,
                     '2026-10-01T12:00:00Z', '2026-10-01T12:00:00Z'),
                    (11, 101, 30, 40, 'ORDER', 'ML', 'SENT_TO_MANAGER', 3, 3,
                     NULL, NULL, NULL, NULL, 10.00, NULL, TRUE, NULL,
                     '2026-10-02T12:00:00Z', '2026-10-02T12:00:00Z'),
                    (12, 102, 30, 40, 'ORDER', 'ML', 'SENT_TO_MANAGER', 4, 4,
                     NULL, NULL, NULL, NULL, 10.00, NULL, TRUE, NULL,
                     '2026-10-03T12:00:00Z', '2026-10-03T12:00:00Z'),
                    (13, 103, 30, 40, 'MONITOR', 'ML', 'GENERATED', NULL, NULL,
                     NULL, NULL, NULL, NULL, NULL, NULL, FALSE, NULL,
                     '2026-10-04T12:00:00Z', '2026-10-04T12:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO suggestion_log(id, suggestion_id, event)
                VALUES
                    (1, 10, 'GENERATED'),
                    (2, 11, 'GENERATED'),
                    (3, 12, 'EXPIRED'),
                    (4, 13, 'GENERATED')
                """
            )
            connection.execute(
                """
                INSERT INTO suggestion_triage(
                    id, suggestion_id, employee_id, last_action,
                    forwarded_at, updated_at
                ) VALUES (
                    1, 11, 8, 'FORWARD',
                    '2026-10-02T13:00:00Z', '2026-10-02T13:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO batch(
                    id, product_id, store_id, expiration_date,
                    current_balance, active
                ) VALUES (
                    1, 40, 30, '2026-12-31', 25, TRUE
                )
                """
            )
            connection.execute("GRANT USAGE ON SCHEMA public TO ai_product_reader")
            connection.execute(
                "GRANT SELECT ON user_account, user_store, store, category, "
                "product, suggestion, suggestion_log, suggestion_triage, batch "
                "TO ai_product_reader"
            )

        connection_params = conninfo_to_dict(admin_dsn)
        connection_params["user"] = "ai_product_reader"
        connection_params["password"] = "test-only-password"
        reader_dsn = make_conninfo(**connection_params)
        pool = ConnectionPool(conninfo=reader_dsn, min_size=1, max_size=2, timeout=3)
        try:
            repository = PostgresProductWorkflowRepository(pool)
            suggestions = repository.search_product_suggestions(
                ProductWorkflowContext(
                    email="reader@example.test",
                    role_id=2,
                    request_id="request-1",
                    trace_id="trace-1",
                ),
                "Leite",
            )

            assert [item.suggestion_id for item in suggestions] == [11]
            detail = repository.get_product_suggestion_detail(
                ProductWorkflowContext(
                    email="reader@example.test",
                    role_id=2,
                    request_id="request-2",
                    trace_id="trace-2",
                ),
                11,
            )
            assert detail is not None
            assert detail.employee_name == "Funcionária Teste"
            assert detail.last_action == "FORWARD"

            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with pool.connection() as connection:
                    connection.execute(
                        "UPDATE suggestion SET current_batch_count = 99 WHERE id = 11"
                    )
        finally:
            pool.close()
