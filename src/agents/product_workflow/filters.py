"""Shared SQL policy fragments for the Product Workflow repository."""

from __future__ import annotations

EMPLOYEE_ROLE_CODE = "EMPLOYEE"
MANAGER_ROLE_CODE = "MANAGER"
MAX_PRODUCT_QUERY_LENGTH = 200
PRODUCT_SEARCH_PAGE_SIZE = 6
MAX_PRODUCT_SEARCH_PAGE = 100
STATEMENT_TIMEOUT_MS = 5_000

AUTHORIZED_SUGGESTION_FROM = """
FROM "suggestion_context" AS s
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
"""

ALLOWED_SUGGESTION_TYPES_CLAUSE = "s.type::text IN ('ORDER', 'PROMOTION')"
NOT_EXPIRED_SUGGESTION_CLAUSE = """
NOT EXISTS (
    SELECT 1
    FROM "suggestion_log" AS expired_log
    WHERE expired_log.suggestion_id = s.id
      AND expired_log.event::text = 'EXPIRED'
)
"""


def visibility_clause(role_code: str) -> str:
    """Return the fixed visibility predicate for an authenticated role."""

    if role_code == EMPLOYEE_ROLE_CODE:
        return (
            "s.available_for_triage IS TRUE AND s.status::text = 'IN_EMPLOYEE_TRIAGE'"
        )
    if role_code == MANAGER_ROLE_CODE:
        return "s.status::text = 'SENT_TO_MANAGER'"
    raise PermissionError("Cargo sem acesso ao Product Workflow")
