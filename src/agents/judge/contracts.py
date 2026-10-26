from typing import Literal, NotRequired, TypedDict

JudgeStatus = Literal["approved", "insufficient_evidence", "invalid"]


class JudgeResponse(TypedDict):
    """Execution result returned by the judge executor to its graph node."""

    status: JudgeStatus
    reason: str
    evidence_count: int
    error_code: NotRequired[str]
    reason_code: NotRequired[str]
    noul_probability: NotRequired[float]
    model: NotRequired[str]
    input_tokens: NotRequired[int | None]
    output_tokens: NotRequired[int | None]
