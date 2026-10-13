"""Deprecated repository kept only for compatibility with historical tests.

The active SQL boundary is ``PostgresProductWorkflowRepository`` in the
parent package. It is the only repository wired into the runtime.
"""

from __future__ import annotations

from typing import Any

from src.agents.product_workflow.schemas import ProductCard
from src.auth.permissions import PRODUCT_WORKFLOW_ROLE_CODES

MAX_PRODUCT_QUERY_LENGTH = 200


class ProductCardRepository:
    """Fixed read-only lookup scoped to the authenticated user's active stores."""

    SQL = """
        SELECT DISTINCT ON (p.id) p.id, s.id, p.name, c.name, p.sku, s.type,
               COALESCE(s.current_batch_count, s.ml_batch_count),
               current_batch.expiration_date,
               COALESCE(s.current_discount_percentage, s.ml_discount_percentage),
               s.reference_sale_price, s.promotional_price,
               s.promotion_valid_from, s.promotion_valid_until
          FROM suggestion s
          JOIN product p ON p.id = s.product_id
          JOIN store st ON st.id = s.store_id AND st.status::text = 'ACTIVE'
          LEFT JOIN category c ON c.id = p.category_id
          LEFT JOIN LATERAL (
               SELECT MIN(b.expiration_date) AS expiration_date
                 FROM batch b
                WHERE b.product_id = p.id AND b.store_id = s.store_id
                  AND b.active = TRUE AND b.current_balance > 0
           ) current_batch ON TRUE
         WHERE EXISTS (
               SELECT 1 FROM user_account ua
               JOIN role r ON r.id = ua.role_id
               JOIN user_store us ON us.user_id = ua.id
                WHERE ua.email = %s AND r.code = %s
                  AND ua.status::text = 'ACTIVE'
                  AND us.store_id = s.store_id AND us.active = TRUE
                  AND us.unassigned_at IS NULL
           )
           AND s.store_id = ANY(%s::bigint[])
           AND (p.name ILIKE %s OR p.sku ILIKE %s OR c.name ILIKE %s)
           AND NOT EXISTS (
               SELECT 1 FROM suggestion_log sl
                WHERE sl.suggestion_id = s.id AND sl.event = 'EXPIRED'
           )
           AND ((%s = 'EMPLOYEE' AND s.available_for_triage = TRUE)
             OR (%s = 'MANAGER' AND s.status = 'SENT_TO_MANAGER'))
         ORDER BY p.id, s.created_at DESC
         LIMIT 6
    """

    def __init__(self, pool: Any, *, statement_timeout_ms: int = 2000):
        self._pool = pool
        self._statement_timeout_ms = statement_timeout_ms

    def search(
        self,
        *,
        email: str,
        role_code: str,
        store_ids: tuple[int, ...],
        product_query: str,
    ) -> list[ProductCard]:
        if role_code not in PRODUCT_WORKFLOW_ROLE_CODES:
            raise PermissionError("Cargo sem acesso a sugestões de produto")
        if not store_ids or any(
            type(store_id) is not int or store_id < 1 for store_id in store_ids
        ):
            raise PermissionError("Lojas autorizadas não disponíveis")
        query = product_query.strip()
        if not query or len(query) > MAX_PRODUCT_QUERY_LENGTH:
            raise ValueError("Consulta de produto inválida")
        with self._pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true)",
                (f"{self._statement_timeout_ms}ms",),
            )
            pattern = f"%{query}%"
            cursor.execute(
                self.SQL,
                (
                    email,
                    role_code,
                    list(store_ids),
                    pattern,
                    pattern,
                    pattern,
                    role_code,
                    role_code,
                ),
            )
            rows = cursor.fetchall()
        return [
            ProductCard(
                product_id=int(row[0]),
                suggestion_id=int(row[1]),
                product_name=str(row[2]),
                category_name=row[3],
                sku=row[4],
                suggestion_type=str(row[5]),
                batch_count=row[6],
                expiration_date=row[7],
                discount_percentage=row[8],
                reference_sale_price=row[9],
                promotional_price=row[10],
                promotion_valid_from=row[11],
                promotion_valid_until=row[12],
            )
            for row in rows
        ]
