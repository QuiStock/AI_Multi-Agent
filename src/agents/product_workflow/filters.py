"""Shared SQL policy fragments for the Product Workflow repository."""

from __future__ import annotations

EMPLOYEE_ROLE_ID = 3
MANAGER_ROLE_ID = 2
MAX_PRODUCT_QUERY_LENGTH = 200
MAX_SUGGESTION_RESULTS = 6

ALLOWED_SUGGESTION_TYPES_CLAUSE = "s.type::text IN ('ORDER', 'PROMOTION')"
NOT_EXPIRED_SUGGESTION_CLAUSE = """
NOT EXISTS (
    SELECT 1
    FROM "suggestion_log" AS expired_log
    WHERE expired_log.suggestion_id = s.id
      AND expired_log.event::text = 'EXPIRED'
)
"""


def visibility_clause(role_id: int) -> str:
    """Return the fixed visibility predicate for an authenticated role."""

    if role_id == EMPLOYEE_ROLE_ID:
        return (
            "s.available_for_triage IS TRUE AND s.status::text = 'IN_EMPLOYEE_TRIAGE'"
        )
    if role_id == MANAGER_ROLE_ID:
        return "s.status::text = 'SENT_TO_MANAGER'"
    raise PermissionError("Cargo sem acesso ao Product Workflow")
