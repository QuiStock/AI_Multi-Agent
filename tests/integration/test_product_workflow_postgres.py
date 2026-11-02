from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import ConnectionPool
from testcontainers.community.postgres import PostgresContainer

from src.agents.product_workflow.contracts import ProductWorkflowContext
from src.agents.product_workflow.repository import (
    PostgresProductWorkflowRepository,
)

pytestmark = pytest.mark.integration


def _manager_context(request_id: str) -> ProductWorkflowContext:
    return ProductWorkflowContext(
        email="reader@example.test",
        user_id=7,
        role_code="MANAGER",
        store_ids=(30,),
        request_id=request_id,
        trace_id=request_id,
    )


@pytest.fixture(scope="module")
def product_reader_pool() -> Iterator[ConnectionPool]:
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
                CREATE TABLE product_analysis (
                    id BIGINT PRIMARY KEY,
                    product_id BIGINT NOT NULL,
                    store_id BIGINT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE product_store (
                    id BIGINT PRIMARY KEY,
                    product_id BIGINT NOT NULL,
                    store_id BIGINT NOT NULL
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
                    product_store_id BIGINT,
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
                    updated_at TIMESTAMPTZ,
                    desired_order_date DATE
                )
                """
            )
            connection.execute(
                """
                CREATE VIEW suggestion_context AS
                SELECT
                    s.id,
                    s.product_analysis_id,
                    s.product_store_id,
                    COALESCE(pa.product_id, ps.product_id) AS product_id,
                    COALESCE(pa.store_id, ps.store_id) AS store_id,
                    s.type,
                    s.origin,
                    s.status,
                    s.ml_batch_count,
                    s.current_batch_count,
                    s.ml_discount_percentage,
                    s.current_discount_percentage,
                    s.promotion_valid_from,
                    s.promotion_valid_until,
                    s.reference_sale_price,
                    s.promotional_price,
                    s.available_for_triage,
                    s.created_by_id,
                    s.created_at,
                    s.updated_at,
                    s.desired_order_date
                FROM suggestion AS s
                LEFT JOIN product_analysis AS pa
                  ON pa.id = s.product_analysis_id
                LEFT JOIN product_store AS ps
                  ON ps.id = s.product_store_id
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
                VALUES (40, 50, 'SKU-40', 'Leite Integral UHT 1L', TRUE),
                       (41, 50, 'SKU-41', 'Queijo Minas', TRUE)
                """
            )
            connection.execute(
                """
                INSERT INTO product_analysis(id, product_id, store_id)
                VALUES (100, 40, 30), (101, 40, 30), (102, 40, 30),
                       (103, 40, 30), (200, 41, 30), (201, 41, 30)
                """
            )
            connection.execute(
                """
                INSERT INTO suggestion(
                    id, product_analysis_id, product_store_id, type, origin,
                    status, ml_batch_count, current_batch_count,
                    ml_discount_percentage, current_discount_percentage,
                    promotion_valid_from, promotion_valid_until,
                    reference_sale_price, promotional_price, available_for_triage,
                    created_by_id, created_at, updated_at
                ) VALUES
                    (10, 100, NULL, 'ORDER', 'ML', 'SENT_TO_MANAGER', 2, 2,
                     NULL, NULL, NULL, NULL, 10.00, NULL, TRUE, NULL,
                     '2026-10-01T12:00:00Z', '2026-10-01T12:00:00Z'),
                    (11, 101, NULL, 'ORDER', 'ML', 'SENT_TO_MANAGER', 3, 3,
                     NULL, NULL, NULL, NULL, 10.00, NULL, TRUE, NULL,
                     '2026-10-02T12:00:00Z', '2026-10-02T12:00:00Z'),
                    (12, 102, NULL, 'ORDER', 'ML', 'SENT_TO_MANAGER', 4, 4,
                     NULL, NULL, NULL, NULL, 10.00, NULL, TRUE, NULL,
                     '2026-10-03T12:00:00Z', '2026-10-03T12:00:00Z'),
                    (13, 103, NULL, 'MONITOR', 'ML', 'GENERATED', NULL, NULL,
                     NULL, NULL, NULL, NULL, NULL, NULL, FALSE, NULL,
                     '2026-10-04T12:00:00Z', '2026-10-04T12:00:00Z'),
                    (20, 200, NULL, 'PROMOTION', 'ML', 'SENT_TO_MANAGER',
                     NULL, NULL, NULL, NULL, '2026-10-01', '2026-11-01',
                     12.00, 9.00, TRUE, NULL,
                     '2026-10-05T12:00:00Z', '2026-10-05T12:00:00Z'),
                    (21, 201, NULL, 'PROMOTION', 'ML', 'SENT_TO_MANAGER',
                     NULL, NULL, NULL, NULL, '2026-10-01', '2026-12-15',
                     15.00, 11.00, TRUE, NULL,
                     '2026-10-06T12:00:00Z', '2026-10-06T12:00:00Z')
                """
            )
            connection.execute(
                "INSERT INTO product_store(id, product_id, store_id) "
                "VALUES (300, 40, 30)"
            )
            connection.execute(
                """
                INSERT INTO suggestion(
                    id, product_analysis_id, product_store_id, type, origin,
                    status, available_for_triage, created_by_id, created_at
                ) VALUES (
                    30, NULL, 300, 'ORDER', 'MANAGER', 'APPROVED', TRUE, 7,
                    '2026-10-07T12:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO suggestion_log(id, suggestion_id, event)
                VALUES
                    (1, 10, 'GENERATED'),
                    (2, 11, 'GENERATED'),
                    (3, 12, 'EXPIRED'),
                    (4, 13, 'GENERATED'),
                    (5, 20, 'GENERATED'),
                    (6, 21, 'GENERATED')
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
                "product, suggestion, suggestion_context, suggestion_log, "
                "suggestion_triage, batch "
                "TO ai_product_reader"
            )

        connection_params = conninfo_to_dict(admin_dsn)
        connection_params["user"] = "ai_product_reader"
        connection_params["password"] = "test-only-password"
        reader_dsn = make_conninfo(**connection_params)
        pool = ConnectionPool(conninfo=reader_dsn, min_size=1, max_size=2, timeout=3)
        try:
            yield pool
        finally:
            pool.close()


def test_product_workflow_reads_postgres_with_select_only_grants(
    product_reader_pool: ConnectionPool,
) -> None:
    repository = PostgresProductWorkflowRepository(product_reader_pool)
    suggestions = repository.search_product_suggestions(
        _manager_context("request-1"),
        "Leite",
    )

    assert [item.suggestion_id for item in suggestions] == [10, 11]
    detail = repository.get_product_suggestion_detail(
        _manager_context("request-2"),
        11,
    )
    assert detail is not None
    assert detail.employee_name == "Funcionária Teste"
    assert detail.last_action == "FORWARD"

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with product_reader_pool.connection() as connection:
            connection.execute(
                "UPDATE suggestion SET current_batch_count = 99 WHERE id = 11"
            )


def test_suggestion_context_view_resolves_manual_product_store_source(
    product_reader_pool: ConnectionPool,
) -> None:
    with product_reader_pool.connection() as connection:
        row = connection.execute(
            "SELECT product_id, store_id FROM suggestion_context WHERE id = 30"
        ).fetchone()

    assert row == (40, 30)


def test_product_workflow_lists_orders_and_promotions(
    product_reader_pool: ConnectionPool,
) -> None:
    repository = PostgresProductWorkflowRepository(product_reader_pool)

    orders = repository.list_product_suggestions(
        _manager_context("request-list-orders"),
        "ORDER",
    )
    promotions = repository.list_product_suggestions(
        _manager_context("request-list-promotions"),
        "PROMOTION",
    )

    assert [item.suggestion_id for item in orders] == [10, 11]
    assert [item.suggestion_id for item in promotions] == [20, 21]


def test_product_workflow_filters_promotions_by_expiration(
    product_reader_pool: ConnectionPool,
) -> None:
    repository = PostgresProductWorkflowRepository(product_reader_pool)
    floor = date(2026, 10, 30)

    nearest = repository.find_promotions_by_expiration(
        _manager_context("request-nearest"),
        "nearest",
        reference_date=floor,
    )
    longest = repository.find_promotions_by_expiration(
        _manager_context("request-longest"),
        "longest",
        reference_date=floor,
    )
    until_november = repository.find_promotions_by_expiration(
        _manager_context("request-until"),
        reference_date=floor,
        until=date(2026, 11, 30),
    )

    assert [item.suggestion_id for item in nearest] == [20]
    assert [item.suggestion_id for item in longest] == [21]
    assert [item.suggestion_id for item in until_november] == [20]
