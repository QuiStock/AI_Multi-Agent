"""Deprecated repository kept only for compatibility with historical tests.

The active SQL boundary is ``PostgresProductWorkflowRepository`` in the
parent package. It is the only repository wired into the runtime.
"""

from __future__ import annotations

from typing import Any

from src.agents.product_workflow.schemas import ProductCard

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
          LEFT JOIN category c ON c.id = p.category_id
          LEFT JOIN LATERAL (
               SELECT MIN(b.expiration_date) AS expiration_date
                 FROM batch b
                WHERE b.product_id = p.id AND b.store_id = s.store_id
                  AND b.active = TRUE AND b.current_balance > 0
           ) current_batch ON TRUE
         WHERE EXISTS (
               SELECT 1 FROM user_account ua
               JOIN user_store us ON us.user_id = ua.id
                WHERE ua.email = %s AND ua.role_id = %s
                  AND us.store_id = s.store_id AND us.active = TRUE
                  AND us.unassigned_at IS NULL
           )
           AND (p.name ILIKE %s OR p.sku ILIKE %s OR c.name ILIKE %s)
           AND NOT EXISTS (
               SELECT 1 FROM suggestion_log sl
                WHERE sl.suggestion_id = s.id AND sl.event = 'EXPIRED'
           )
           AND ((%s = 3 AND s.available_for_triage = TRUE)
             OR (%s = 2 AND s.status = 'SENT_TO_MANAGER'))
         ORDER BY p.id, s.created_at DESC
         LIMIT 6
    """

    def __init__(self, pool: Any, *, statement_timeout_ms: int = 2000):
        self._pool = pool
        self._statement_timeout_ms = statement_timeout_ms

    def search(
        self, *, email: str, role_id: int, product_query: str
    ) -> list[ProductCard]:
        if role_id not in (2, 3):
            raise PermissionError("Cargo sem acesso a sugestões de produto")
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
                (email, role_id, pattern, pattern, pattern, role_id, role_id),
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
