from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol, cast

from .filters import (
    ALLOWED_SUGGESTION_TYPES_CLAUSE,
    MAX_PRODUCT_QUERY_LENGTH,
    MAX_SUGGESTION_RESULTS,
    NOT_EXPIRED_SUGGESTION_CLAUSE,
    visibility_clause,
)
from .models import (
    ProductSuggestionDetailRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)


class ProductWorkflowDependencyError(RuntimeError):
    """The read-only commercial PostgreSQL query could not be completed."""


class ProductWorkflowRepository(Protocol):
    """Read-only operations used by the Product Workflow tools."""

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        limit: int = 6,
    ) -> list[ProductSuggestionSearchRecord]: ...

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None: ...


class PostgresProductWorkflowRepository:
    """Direct, parameterized, read-only access to the commercial PostgreSQL."""

    def __init__(self, pool: Any, *, statement_timeout_ms: int = 2_000):
        self._pool = pool
        self._statement_timeout_ms = statement_timeout_ms

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        limit: int = 6,
    ) -> list[ProductSuggestionSearchRecord]:
        role_id = self._require_supported_role(context)
        query = product_query.strip()
        if not query or len(query) > MAX_PRODUCT_QUERY_LENGTH:
            raise ValueError("Consulta de produto inválida")
        if limit < 1 or limit > MAX_SUGGESTION_RESULTS:
            raise ValueError("Limite de produtos inválido")

        visibility = visibility_clause(role_id)
        escaped_query = (
            query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        sql = f"""
            WITH ranked_suggestions AS (
                SELECT
                    s.id,
                    s.product_id,
                    s.store_id,
                    p.name AS product_name,
                    c.name AS category_name,
                    p.sku,
                    st.name AS store_name,
                    s.type::text,
                    s.status::text,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.product_id, s.store_id
                        ORDER BY
                            COALESCE(s.updated_at, s.created_at) DESC,
                            s.created_at DESC,
                            s.id DESC
                    ) AS suggestion_rank
                FROM "suggestion" AS s
                JOIN "product" AS p
                  ON p.id = s.product_id
                 AND p.active IS TRUE
                LEFT JOIN "category" AS c
                  ON c.id = p.category_id
                 AND c.active IS TRUE
                JOIN "store" AS st
                  ON st.id = s.store_id
                 AND st.status::text = 'ACTIVE'
                JOIN "user_store" AS us
                  ON us.store_id = s.store_id
                 AND us.active IS TRUE
                 AND us.unassigned_at IS NULL
                JOIN "user_account" AS ua
                  ON ua.id = us.user_id
                 AND ua.status::text = 'ACTIVE'
                WHERE LOWER(ua.email) = LOWER(%s)
                  AND ua.role_id = %s
                  AND {visibility}
                  AND {ALLOWED_SUGGESTION_TYPES_CLAUSE}
                  AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
                  AND (
                      p.name ILIKE %s ESCAPE '\\'
                      OR p.sku ILIKE %s ESCAPE '\\'
                      OR c.name ILIKE %s ESCAPE '\\'
                  )
            )
            SELECT
                id,
                product_id,
                store_id,
                product_name,
                category_name,
                sku,
                store_name,
                type,
                status
            FROM ranked_suggestions
            WHERE suggestion_rank = 1
            ORDER BY product_name ASC, sku ASC, store_id ASC, id DESC
            LIMIT %s
        """
        rows = self._fetch_all(
            sql,
            [context.email, role_id, pattern, pattern, pattern, limit],
        )
        return [_search_record_from_row(row) for row in rows]

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None:
        role_id = self._require_supported_role(context)
        visibility = visibility_clause(role_id)
        sql = f"""
            SELECT
                s.id,
                s.product_id,
                s.store_id,
                p.name,
                c.name,
                p.sku,
                st.name,
                s.type::text,
                s.origin::text,
                s.status::text,
                s.ml_batch_count,
                s.current_batch_count,
                s.ml_discount_percentage,
                s.current_discount_percentage,
                s.reference_sale_price,
                s.promotional_price,
                s.promotion_valid_from,
                s.promotion_valid_until,
                current_batch.expiration_date,
                s.available_for_triage,
                s.created_at,
                s.updated_at,
                triage.employee_id,
                employee.name,
                triage.last_action::text,
                triage.forwarded_at,
                triage.updated_at
            FROM "suggestion" AS s
            JOIN "product" AS p
              ON p.id = s.product_id
             AND p.active IS TRUE
            LEFT JOIN "category" AS c
              ON c.id = p.category_id
             AND c.active IS TRUE
            JOIN "store" AS st
              ON st.id = s.store_id
             AND st.status::text = 'ACTIVE'
            JOIN "user_store" AS us
              ON us.store_id = s.store_id
             AND us.active IS TRUE
             AND us.unassigned_at IS NULL
            JOIN "user_account" AS ua
              ON ua.id = us.user_id
             AND ua.status::text = 'ACTIVE'
            LEFT JOIN "suggestion_triage" AS triage
              ON triage.suggestion_id = s.id
            LEFT JOIN "user_account" AS employee
              ON employee.id = triage.employee_id
            LEFT JOIN LATERAL (
                SELECT MIN(b.expiration_date) AS expiration_date
                FROM "batch" AS b
                WHERE b.product_id = s.product_id
                  AND b.store_id = s.store_id
                  AND b.active IS TRUE
                  AND b.current_balance > 0
            ) AS current_batch ON TRUE
            WHERE s.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND ua.role_id = %s
              AND {visibility}
              AND {ALLOWED_SUGGESTION_TYPES_CLAUSE}
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
            LIMIT 1
        """
        row = self._fetch_one(sql, [suggestion_id, context.email, role_id])
        return None if row is None else _detail_record_from_row(row)

    @staticmethod
    def _require_supported_role(context: ProductWorkflowContext) -> int:
        if context.role_id is None:
            raise PermissionError("Cargo sem acesso ao Product Workflow")
        visibility_clause(context.role_id)
        return context.role_id

    def _fetch_all(self, sql: str, params: Sequence[Any]) -> list[tuple[Any, ...]]:
        try:
            with self._pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{self._statement_timeout_ms}ms",),
                )
                cursor.execute(sql, tuple(params))
                return list(cursor.fetchall())
        except Exception as exc:
            raise ProductWorkflowDependencyError from exc

    def _fetch_one(self, sql: str, params: Sequence[Any]) -> tuple[Any, ...] | None:
        try:
            with self._pool.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{self._statement_timeout_ms}ms",),
                )
                cursor.execute(sql, tuple(params))
                return cast(tuple[Any, ...] | None, cursor.fetchone())
        except Exception as exc:
            raise ProductWorkflowDependencyError from exc


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _search_record_from_row(
    row: tuple[Any, ...],
) -> ProductSuggestionSearchRecord:
    return ProductSuggestionSearchRecord(
        suggestion_id=int(row[0]),
        product_id=int(row[1]),
        store_id=int(row[2]),
        product_name=str(row[3]),
        category_name=str(row[4]) if row[4] is not None else None,
        sku=str(row[5]),
        store_name=str(row[6]),
        suggestion_type=cast(Literal["ORDER", "PROMOTION"], str(row[7])),
        suggestion_status=cast(
            Literal[
                "GENERATED",
                "IN_EMPLOYEE_TRIAGE",
                "SENT_TO_MANAGER",
                "APPROVED",
                "REJECTED",
            ],
            str(row[8]),
        ),
    )


def _detail_record_from_row(
    row: tuple[Any, ...],
) -> ProductSuggestionDetailRecord:
    return ProductSuggestionDetailRecord(
        suggestion_id=int(row[0]),
        product_id=int(row[1]),
        store_id=int(row[2]),
        product_name=str(row[3]),
        category_name=str(row[4]) if row[4] is not None else None,
        sku=str(row[5]),
        store_name=str(row[6]),
        suggestion_type=cast(Literal["ORDER", "PROMOTION"], str(row[7])),
        origin=cast(Literal["ML", "EMPLOYEE", "MANAGER"], str(row[8])),
        status=cast(
            Literal[
                "GENERATED",
                "IN_EMPLOYEE_TRIAGE",
                "SENT_TO_MANAGER",
                "APPROVED",
                "REJECTED",
            ],
            str(row[9]),
        ),
        ml_batch_count=int(row[10]) if row[10] is not None else None,
        current_batch_count=int(row[11]) if row[11] is not None else None,
        ml_discount_percentage=_float_or_none(row[12]),
        current_discount_percentage=_float_or_none(row[13]),
        reference_sale_price=_float_or_none(row[14]),
        promotional_price=_float_or_none(row[15]),
        promotion_valid_from=row[16],
        promotion_valid_until=row[17],
        physical_expiration_date=row[18],
        available_for_triage=bool(row[19]),
        created_at=row[20],
        updated_at=row[21],
        employee_id=int(row[22]) if row[22] is not None else None,
        employee_name=str(row[23]) if row[23] is not None else None,
        last_action=(
            cast(Literal["EDIT", "FORWARD"], str(row[24]))
            if row[24] is not None
            else None
        ),
        forwarded_at=row[25],
        triage_updated_at=row[26],
    )
