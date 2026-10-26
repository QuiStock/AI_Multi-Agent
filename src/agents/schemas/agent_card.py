from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .policies import PromptVariable
from .tool_binding import ToolBinding


class AgentRole(StrEnum):
    ROUTER = "router"
    FAQ_RAG = "faq_rag"
    PRODUCT_WORKFLOW = "product_workflow"
    RESPONSE_COMPILER = "response_compiler"


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)

    role: AgentRole

    version: str = Field(
        pattern=r"^\d+\.\d+\.\d+$",
    )

    system_prompt_template: str = Field(min_length=1)

    tools: list[ToolBinding]

    prompt_variables: list[PromptVariable] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_tools(self) -> "AgentCard":
        tool_ids = [tool.id for tool in self.tools]

        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("The AgentCard cannot have duplicated tools")

        return self
