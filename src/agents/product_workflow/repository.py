from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from datetime import date
from typing import Any, Literal, Protocol, cast

from .contracts import (
    ProductSuggestionDetailRecord,
    ProductSuggestionListingRecord,
    ProductSuggestionSearchRecord,
    ProductWorkflowContext,
)
from .filters import (
    ALLOWED_SUGGESTION_TYPES_CLAUSE,
    AUTHORIZED_SUGGESTION_FROM,
    MAX_PRODUCT_QUERY_LENGTH,
    MAX_PRODUCT_SEARCH_PAGE,
    NOT_EXPIRED_SUGGESTION_CLAUSE,
    PRODUCT_SEARCH_PAGE_SIZE,
    STATEMENT_TIMEOUT_MS,
    visibility_clause,
)

_SEARCH_ACCENTS = "ÁÀÂÃÄáàâãäÉÈÊËéèêëÍÌÎÏíìîïÓÒÔÕÖóòôõöÚÙÛÜúùûüÇçÑñ"
_SEARCH_PLAIN = "AAAAAaaaaaEEEEeeeeIIIIiiiiOOOOOoooooUUUUuuuuCcNn"


def _fold_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return normalized.translate(str.maketrans(_SEARCH_ACCENTS, _SEARCH_PLAIN))


class ProductWorkflowDependencyError(RuntimeError):
    """The read-only commercial PostgreSQL query could not be completed."""


class ProductWorkflowRepository(Protocol):
    """Read-only operations used by the Product Workflow tools."""

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        page: int = 1,
    ) -> list[ProductSuggestionSearchRecord]: ...

    def get_product_suggestion_detail(
        self,
        context: ProductWorkflowContext,
        suggestion_id: int,
    ) -> ProductSuggestionDetailRecord | None: ...

    def list_product_suggestions(
        self,
        context: ProductWorkflowContext,
        suggestion_type: str | Sequence[str],
        *,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]: ...

    def find_promotions_by_expiration(
        self,
        context: ProductWorkflowContext,
        direction: Literal["nearest", "longest"] | None = None,
        *,
        reference_date: date | None = None,
        until: date | None = None,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]: ...


class PostgresProductWorkflowRepository:
    """Direct, parameterized, read-only access to the commercial PostgreSQL."""

    def __init__(
        self,
        pool: Any,
        *,
        statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    ):
        self._pool = pool
        self._statement_timeout_ms = statement_timeout_ms

    def search_product_suggestions(
        self,
        context: ProductWorkflowContext,
        product_query: str,
        *,
        page: int = 1,
    ) -> list[ProductSuggestionSearchRecord]:
        role_code = self._require_supported_role(context)
        query = product_query.strip()
        if not query or len(query) > MAX_PRODUCT_QUERY_LENGTH:
            raise ValueError("Consulta de produto inválida")
        if type(page) is not int or page < 1 or page > MAX_PRODUCT_SEARCH_PAGE:
            raise ValueError("Página de produtos inválida")
        offset = (page - 1) * PRODUCT_SEARCH_PAGE_SIZE

        visibility = visibility_clause(role_code)
        escaped_query = (
            _fold_search_text(query)
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        sql = f"""
            SELECT
                s.id,
                s.product_id,
                p.name AS product_name,
                c.name AS category_name,
                p.sku,
                s.type::text,
                s.status::text
            {AUTHORIZED_SUGGESTION_FROM}
            WHERE ua.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND s.store_id = ANY(%s)
              AND {visibility}
              AND {ALLOWED_SUGGESTION_TYPES_CLAUSE}
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
              AND (
                  translate(p.name, %s, %s) ILIKE %s ESCAPE '\\'
                  OR translate(p.sku, %s, %s) ILIKE %s ESCAPE '\\'
              )
            ORDER BY p.name ASC, p.sku ASC, s.store_id ASC, s.id ASC
            LIMIT %s
            OFFSET %s
        """
        rows = self._fetch_all(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                _SEARCH_ACCENTS,
                _SEARCH_PLAIN,
                pattern,
                _SEARCH_ACCENTS,
                _SEARCH_PLAIN,
                pattern,
                PRODUCT_SEARCH_PAGE_SIZE + 1,
                offset,
            ],
        )
        return [_search_record_from_row(row) for row in rows]

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
            {AUTHORIZED_SUGGESTION_FROM}
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
        suggestion_type: str | Sequence[str],
        *,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]:
        role_code = self._require_supported_role(context)
        suggestion_types = normalize_suggestion_types(suggestion_type)
        offset = _page_offset(page)
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
            {AUTHORIZED_SUGGESTION_FROM}
            WHERE ua.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND s.store_id = ANY(%s)
              AND {visibility}
              AND s.type::text = ANY(%s)
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
            ORDER BY p.name ASC, p.sku ASC, s.store_id ASC, s.id ASC
            LIMIT %s
            OFFSET %s
        """
        rows = self._fetch_all(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                suggestion_types,
                PRODUCT_SEARCH_PAGE_SIZE + 1,
                offset,
            ],
        )
        return [_listing_record_from_row(row) for row in rows]

    def find_promotions_by_expiration(
        self,
        context: ProductWorkflowContext,
        direction: Literal["nearest", "longest"] | None = None,
        *,
        reference_date: date | None = None,
        until: date | None = None,
        page: int = 1,
    ) -> list[ProductSuggestionListingRecord]:
        role_code = self._require_supported_role(context)
        floor = reference_date or date.today()
        offset = _page_offset(page)
        if until is not None:
            return self._promotions_until(
                context,
                role_code=role_code,
                floor=floor,
                until=until,
                offset=offset,
            )
        if direction != "nearest" and direction != "longest":  # noqa: PLR1714
            raise ValueError("Direção de validade inválida")
        return self._promotions_by_extreme(
            context,
            role_code=role_code,
            floor=floor,
            direction=direction,
            offset=offset,
        )

    def _promotions_by_extreme(
        self,
        context: ProductWorkflowContext,
        *,
        role_code: str,
        floor: date,
        direction: Literal["nearest", "longest"],
        offset: int,
    ) -> list[ProductSuggestionListingRecord]:
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
                {AUTHORIZED_SUGGESTION_FROM}
                WHERE ua.id = %s
                  AND LOWER(ua.email) = LOWER(%s)
                  AND s.store_id = ANY(%s)
                  AND {visibility}
                  AND s.type::text = 'PROMOTION'
                  AND s.promotion_valid_until >= %s
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
            ORDER BY v.product_name ASC, v.sku ASC, v.store_id ASC, v.id ASC
            LIMIT %s
            OFFSET %s
        """
        return self._promotion_rows(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                floor,
                PRODUCT_SEARCH_PAGE_SIZE + 1,
                offset,
            ],
        )

    def _promotions_until(
        self,
        context: ProductWorkflowContext,
        *,
        role_code: str,
        floor: date,
        until: date,
        offset: int,
    ) -> list[ProductSuggestionListingRecord]:
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
            {AUTHORIZED_SUGGESTION_FROM}
            WHERE ua.id = %s
              AND LOWER(ua.email) = LOWER(%s)
              AND s.store_id = ANY(%s)
              AND {visibility}
              AND s.type::text = 'PROMOTION'
              AND s.promotion_valid_until >= %s
              AND s.promotion_valid_until <= %s
              AND {NOT_EXPIRED_SUGGESTION_CLAUSE}
            ORDER BY
                s.promotion_valid_until ASC,
                p.name ASC,
                p.sku ASC,
                s.store_id ASC,
                s.id ASC
            LIMIT %s
            OFFSET %s
        """
        return self._promotion_rows(
            sql,
            [
                context.user_id,
                context.email,
                list(context.store_ids),
                floor,
                until,
                PRODUCT_SEARCH_PAGE_SIZE + 1,
                offset,
            ],
        )

    def _promotion_rows(
        self,
        sql: str,
        params: list[Any],
    ) -> list[ProductSuggestionListingRecord]:
        return [_listing_record_from_row(row) for row in self._fetch_all(sql, params)]

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
        product_name=str(row[2]),
        category_name=str(row[3]) if row[3] is not None else None,
        sku=str(row[4]),
        suggestion_type=cast(Literal["ORDER", "PROMOTION"], str(row[5])),
        suggestion_status=cast(
            Literal[
                "GENERATED",
                "IN_EMPLOYEE_TRIAGE",
                "SENT_TO_MANAGER",
                "APPROVED",
                "REJECTED",
            ],
            str(row[6]),
        ),
    )


def _listing_record_from_row(
    row: tuple[Any, ...],
) -> ProductSuggestionListingRecord:
    return ProductSuggestionListingRecord(
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
        promotion_valid_until=row[9] if len(row) > 9 else None,  # noqa: PLR2004
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


def normalize_suggestion_types(
    suggestion_type: str | Sequence[object],
) -> list[Literal["ORDER", "PROMOTION"]]:
    """Accept one type, or both, and return them in stable order."""

    if isinstance(suggestion_type, str):
        raw: list[object] = [suggestion_type]
    elif isinstance(suggestion_type, Sequence):
        raw = list(suggestion_type)
    else:
        raise ValueError("Tipo de sugestão inválido")
    if not raw:
        raise ValueError("Tipo de sugestão inválido")
    seen: list[Literal["ORDER", "PROMOTION"]] = []
    for item in raw:
        if item not in ("ORDER", "PROMOTION") or item in seen:
            raise ValueError("Tipo de sugestão inválido")
        seen.append(cast(Literal["ORDER", "PROMOTION"], item))
    return [item for item in ("ORDER", "PROMOTION") if item in seen]


def _page_offset(page: int) -> int:
    if type(page) is not int or page < 1 or page > MAX_PRODUCT_SEARCH_PAGE:
        raise ValueError("Página de produtos inválida")
    return (page - 1) * PRODUCT_SEARCH_PAGE_SIZE
