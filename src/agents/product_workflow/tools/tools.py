"""Load the four read-only Product Workflow tools."""

from __future__ import annotations

from datetime import date

from langchain_core.tools import BaseTool

from src.agents.product_workflow.repository import ProductWorkflowRepository

from ..contracts import ProductWorkflowContext
from .get_promotion_by_expiration import create_get_promotion_by_expiration_tool
from .get_suggestion_detail import create_get_suggestion_detail_tool
from .get_suggestion_for_product import create_get_suggestion_for_product_tool
from .list_suggestions import create_list_suggestions_tool
from .schemas import OnToolResult


def build_product_workflow_tools(
    *,
    repository: ProductWorkflowRepository,
    context: ProductWorkflowContext,
    reference_date: date | None = None,
    on_result: OnToolResult | None = None,
) -> list[BaseTool]:
    return [
        create_get_suggestion_for_product_tool(
            repository=repository,
            context=context,
            on_result=on_result,
        ),
        create_get_suggestion_detail_tool(
            repository=repository,
            context=context,
            on_result=on_result,
        ),
        create_list_suggestions_tool(
            repository=repository,
            context=context,
            on_result=on_result,
        ),
        create_get_promotion_by_expiration_tool(
            repository=repository,
            context=context,
            reference_date=reference_date or date.today(),
            on_result=on_result,
        ),
    ]
