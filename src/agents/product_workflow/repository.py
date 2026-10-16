from __future__ import annotations

import base64
import json
import logging
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal, Protocol, cast

from .filters import (
    ALLOWED_SUGGESTION_TYPES_CLAUSE,
    MAX_CURSOR_LENGTH,
    MAX_PRODUCT_QUERY_LENGTH,
    MAX_PROMOTION_TIE_PAGE_SIZE,
    MAX_SUGGESTION_PAGE_SIZE,
    MAX_SUGGESTION_RESULTS,
    NOT_EXPIRED_SUGGESTION_CLAUSE,
    visibility_clause,
)
from .models import (
    ProductSuggestionDetailRecord,
    ProductSuggestionPage,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)

logger = logging.getLogger(__name__)


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

    def list_product_suggestions(
        self,
        context: ProductWorkflowContext,
        suggestion_type: Literal["ORDER", "PROMOTION"],
        *,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> ProductSuggestionPage: ...

    def find_promotions_by_expiration(
        self,
        context: ProductWorkflowContext,
        direction: Literal["nearest", "longest"],
        *,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> ProductSuggestionPage: ...


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
        role_code = self._require_supported_role(context)
        query = product_query.strip()
        if not query or len(query) > MAX_PRODUCT_QUERY_LENGTH:
            raise ValueError("Consulta de produto inválida")
        if limit < 1 or limit > MAX_SUGGESTION_RESULTS:
            raise ValueError("Limite de produtos inválido")

        visibility = visibility_clause(role_code)
        escaped_query = (
            query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        numeric_reference: int | None = None
        if query.isdecimal():
            parsed_reference = int(query)
            if parsed_reference > 0:
                numeric_reference = parsed_reference
        identifier_clause = ""
        identifier_params: list[Any] = []
        if numeric_reference is not None:
            identifier_clause = "OR p.id = %s OR s.id = %s"
            identifier_params = [numeric_reference, numeric_reference]
        sql = f"""
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
                s.promotion_valid_until
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
            WHERE ua.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND s.store_id = ANY(%s)
              AND {visibility}
              AND {ALLOWED_SUGGESTION_TYPES_CLAUSE}
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
              AND (
                  p.name ILIKE %s ESCAPE '\\'
                  OR p.sku ILIKE %s ESCAPE '\\'
                  OR c.name ILIKE %s ESCAPE '\\'
                  {identifier_clause}
              )
            ORDER BY product_name ASC, p.sku ASC, s.store_id ASC, s.id ASC
            LIMIT %s
        """
        rows = self._fetch_all(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                pattern,
                pattern,
                pattern,
                *identifier_params,
                limit,
            ],
        )
        if not rows:
            self._log_empty_product_search_diagnostics(
                context=context,
                pattern=pattern,
                role_code=role_code,
                numeric_reference=numeric_reference,
            )
        return [_search_record_from_row(row) for row in rows]

    def _log_empty_product_search_diagnostics(
        self,
        *,
        context: ProductWorkflowContext,
        pattern: str,
        role_code: str,
        numeric_reference: int | None,
    ) -> None:
        """Log scoped aggregate counts explaining an empty eligible lookup."""
        visibility = visibility_clause(role_code)
        identifier_clause = ""
        identifier_params: list[Any] = []
        if numeric_reference is not None:
            identifier_clause = "OR p.id = %s OR s.id = %s"
            identifier_params = [numeric_reference, numeric_reference]
        sql = f"""
            WITH query_scope AS (
                SELECT
                    s.id,
                    s.store_id,
                    s.type::text AS type,
                    s.status::text AS status,
                    s.available_for_triage
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
                WHERE s.store_id = ANY(%s)
                  AND (
                      p.name ILIKE %s ESCAPE '\\'
                      OR p.sku ILIKE %s ESCAPE '\\'
                      OR c.name ILIKE %s ESCAPE '\\'
                      {identifier_clause}
                  )
            ), user_store_scope AS (
                SELECT s.*
                FROM query_scope AS s
                WHERE EXISTS (
                    SELECT 1
                    FROM "user_account" AS ua
                    JOIN "user_store" AS us
                      ON us.user_id = ua.id
                     AND us.store_id = s.store_id
                     AND us.active IS TRUE
                     AND us.unassigned_at IS NULL
                    WHERE ua.id = %s
                      AND LOWER(ua.email) = LOWER(%s)
                      AND ua.status::text = 'ACTIVE'
                )
            ), supported_type AS (
                SELECT s.*
                FROM user_store_scope AS s
                WHERE {ALLOWED_SUGGESTION_TYPES_CLAUSE}
            ), role_visible AS (
                SELECT s.*
                FROM supported_type AS s
                WHERE {visibility}
            ), not_expired AS (
                SELECT s.*
                FROM role_visible AS s
                WHERE {NOT_EXPIRED_SUGGESTION_CLAUSE}
            )
            SELECT
                (SELECT COUNT(*) FROM query_scope),
                (SELECT COUNT(*) FROM user_store_scope),
                (SELECT COUNT(*) FROM supported_type),
                (SELECT COUNT(*) FROM role_visible),
                (SELECT COUNT(*) FROM not_expired)
        """
        try:
            row = self._fetch_one(
                sql,
                [
                    list(context.store_ids),
                    pattern,
                    pattern,
                    pattern,
                    *identifier_params,
                    context.user_id,
                    context.email,
                ],
            )
        except ProductWorkflowDependencyError as exc:
            logger.warning(
                "product_workflow_lookup_filter_diagnostics_failed",
                extra={
                    "event": "product_workflow_lookup_filter_diagnostics_failed",
                    "error_type": type(exc).__name__,
                },
            )
            return

        if row is None or len(row) != 5:
            logger.warning(
                "product_workflow_lookup_filter_diagnostics_failed",
                extra={
                    "event": "product_workflow_lookup_filter_diagnostics_failed",
                    "error_type": "UnexpectedDiagnosticResult",
                },
            )
            return

        counts = [int(value or 0) for value in row]
        if counts[0] == 0:
            excluded_at_stage = "authorized_store_product_match"
        elif counts[1] == 0:
            excluded_at_stage = "active_user_store_assignment"
        elif counts[2] == 0:
            excluded_at_stage = "supported_suggestion_type"
        elif counts[3] == 0:
            excluded_at_stage = "role_visibility"
        elif counts[4] == 0:
            excluded_at_stage = "expired_suggestion"
        else:
            excluded_at_stage = "search_query_filter_mismatch"

        logger.info(
            "product_workflow_lookup_filter_diagnostics",
            extra={
                "event": "product_workflow_lookup_filter_diagnostics",
                "excluded_at_stage": excluded_at_stage,
                "role_code": role_code,
                "authorized_store_count": len(context.store_ids),
                "query_scope_match_count": counts[0],
                "user_store_match_count": counts[1],
                "supported_type_match_count": counts[2],
                "role_visible_match_count": counts[3],
                "not_expired_match_count": counts[4],
            },
        )

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None:
        role_code = self._require_supported_role(context)
        visibility = visibility_clause(role_code)
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
              AND ua.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND s.store_id = ANY(%s)
              AND {visibility}
              AND {ALLOWED_SUGGESTION_TYPES_CLAUSE}
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
            LIMIT 1
        """
        row = self._fetch_one(
            sql,
            [suggestion_id, context.user_id, context.email, list(context.store_ids)],
        )
        return None if row is None else _detail_record_from_row(row)

    def list_product_suggestions(
        self,
        context: ProductWorkflowContext,
        suggestion_type: Literal["ORDER", "PROMOTION"],
        *,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> ProductSuggestionPage:
        role_code = self._require_supported_role(context)
        if suggestion_type not in ("ORDER", "PROMOTION"):
            raise ValueError("Tipo de sugestão inválido")
        if page_size < 1 or page_size > MAX_SUGGESTION_PAGE_SIZE:
            raise ValueError("Tamanho da página inválido")

        cursor_key = _decode_keyset_cursor(
            cursor,
            kind="suggestion_list",
            filter_value=suggestion_type,
        )
        cursor_clause = ""
        cursor_params: list[Any] = []
        if cursor_key is not None:
            cursor_clause = """
                AND (p.name, p.sku, s.store_id, s.id) > (%s, %s, %s, %s)
            """
            cursor_params = list(cursor_key)

        visibility = visibility_clause(role_code)
        sql = f"""
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
                s.promotion_valid_until
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
            WHERE ua.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND s.store_id = ANY(%s)
              AND {visibility}
              AND s.type::text = %s
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
              {cursor_clause}
            ORDER BY p.name ASC, p.sku ASC, s.store_id ASC, s.id ASC
            LIMIT %s
        """
        rows = self._fetch_all(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                suggestion_type,
                *cursor_params,
                page_size + 1,
            ],
        )
        has_more = len(rows) > page_size
        records = [_search_record_from_row(row) for row in rows[:page_size]]
        next_cursor = (
            _encode_keyset_cursor(
                kind="suggestion_list",
                filter_value=suggestion_type,
                record=records[-1],
            )
            if has_more and records
            else None
        )
        return ProductSuggestionPage(
            suggestions=records,
            next_cursor=next_cursor,
        )

    def find_promotions_by_expiration(
        self,
        context: ProductWorkflowContext,
        direction: Literal["nearest", "longest"],
        *,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> ProductSuggestionPage:
        role_code = self._require_supported_role(context)
        if direction not in ("nearest", "longest"):
            raise ValueError("Direção de validade inválida")
        if page_size < 1 or page_size > MAX_PROMOTION_TIE_PAGE_SIZE:
            raise ValueError("Tamanho da página de promoções inválido")

        cursor_data = _decode_expiration_cursor(cursor, direction=direction)
        cursor_clause = ""
        cursor_params: list[Any] = []
        if cursor_data is not None:
            valid_until, cursor_key = cursor_data
            cursor_clause = """
                AND v.promotion_valid_until = %s
                AND (v.product_name, v.sku, v.store_id, v.id) > (%s, %s, %s, %s)
            """
            cursor_params = [valid_until, *cursor_key]

        extreme_aggregate = "MIN" if direction == "nearest" else "MAX"
        visibility = visibility_clause(role_code)
        sql = f"""
            WITH visible_promotions AS (
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
                    s.promotion_valid_until
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
                WHERE ua.id = %s
                  AND LOWER(ua.email) = LOWER(%s)
                  AND s.store_id = ANY(%s)
                  AND {visibility}
                  AND s.type::text = 'PROMOTION'
                  AND s.promotion_valid_until >= CURRENT_DATE
                  AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
            ),
            extreme_validity AS (
                SELECT {extreme_aggregate}(promotion_valid_until) AS valid_until
                FROM visible_promotions
            )
            SELECT
                v.id,
                v.product_id,
                v.store_id,
                v.product_name,
                v.category_name,
                v.sku,
                v.store_name,
                v.type,
                v.status,
                v.promotion_valid_until
            FROM visible_promotions AS v
            CROSS JOIN extreme_validity AS e
            WHERE v.promotion_valid_until = e.valid_until
              {cursor_clause}
            ORDER BY v.product_name ASC, v.sku ASC, v.store_id ASC, v.id ASC
            LIMIT %s
        """
        rows = self._fetch_all(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                *cursor_params,
                page_size + 1,
            ],
        )
        has_more = len(rows) > page_size
        records = [_search_record_from_row(row) for row in rows[:page_size]]
        next_cursor = (
            _encode_expiration_cursor(direction=direction, record=records[-1])
            if has_more and records
            else None
        )
        return ProductSuggestionPage(
            suggestions=records,
            next_cursor=next_cursor,
        )

    @staticmethod
    def _require_supported_role(context: ProductWorkflowContext) -> str:
        visibility_clause(context.role_code)
        return context.role_code

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
        promotion_valid_until=row[9] if len(row) > 9 else None,
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


def _record_key(
    record: ProductSuggestionSearchRecord,
) -> tuple[str, str, int, int]:
    return (
        record.product_name,
        record.sku,
        record.store_id,
        record.suggestion_id,
    )


def _encode_cursor_payload(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    if len(encoded) > MAX_CURSOR_LENGTH:
        raise ValueError("Cursor de paginação excede o tamanho permitido")
    return encoded


def _decode_cursor_payload(cursor: str | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_CURSOR_LENGTH:
        raise ValueError("Cursor de paginação inválido")
    try:
        raw = base64.b64decode(
            cursor.encode("ascii") + b"=" * (-len(cursor) % 4),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("Cursor de paginação inválido") from exc
    if not isinstance(payload, dict):
        raise ValueError("Cursor de paginação inválido")
    return payload


def _validate_record_key(value: object) -> tuple[str, str, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not isinstance(value[0], str)
        or not isinstance(value[1], str)
        or type(value[2]) is not int
        or type(value[3]) is not int
        or value[2] < 1
        or value[3] < 1
    ):
        raise ValueError("Cursor de paginação inválido")
    return value[0], value[1], value[2], value[3]


def _decode_keyset_cursor(
    cursor: str | None,
    *,
    kind: str,
    filter_value: str,
) -> tuple[str, str, int, int] | None:
    payload = _decode_cursor_payload(cursor)
    if payload is None:
        return None
    if payload.get("kind") != kind or payload.get("filter") != filter_value:
        raise ValueError("Cursor de paginação incompatível com a consulta")
    return _validate_record_key(payload.get("key"))


def _encode_keyset_cursor(
    *,
    kind: str,
    filter_value: str,
    record: ProductSuggestionSearchRecord,
) -> str:
    return _encode_cursor_payload(
        {
            "kind": kind,
            "filter": filter_value,
            "key": list(_record_key(record)),
        }
    )


def _decode_expiration_cursor(
    cursor: str | None,
    *,
    direction: Literal["nearest", "longest"],
) -> tuple[date, tuple[str, str, int, int]] | None:
    payload = _decode_cursor_payload(cursor)
    if payload is None:
        return None
    if payload.get("kind") != "promotion_expiration" or payload.get(
        "direction"
    ) != direction:
        raise ValueError("Cursor de validade incompatível com a consulta")
    valid_until_value = payload.get("valid_until")
    if not isinstance(valid_until_value, str):
        raise ValueError("Cursor de validade inválido")
    try:
        valid_until = date.fromisoformat(valid_until_value)
    except ValueError as exc:
        raise ValueError("Cursor de validade inválido") from exc
    return valid_until, _validate_record_key(payload.get("key"))


def _encode_expiration_cursor(
    *,
    direction: Literal["nearest", "longest"],
    record: ProductSuggestionSearchRecord,
) -> str:
    if record.promotion_valid_until is None:
        raise ValueError("Promoção sem data de validade")
    return _encode_cursor_payload(
        {
            "kind": "promotion_expiration",
            "direction": direction,
            "valid_until": record.promotion_valid_until.isoformat(),
            "key": list(_record_key(record)),
        }
    )
