from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src import config
from src.api.dependencies import (
    get_lab_agent_config_service,
    get_lab_run_service,
    get_observability_service,
)
from src.api.schemas.observability import (
    LabAgentConfigResponse,
    LabModelCatalogResponse,
    LabModelOptionResponse,
    LabRunRequest,
    LabRunResponse,
    LiveTraceFeedResponse,
    ObservabilityConversationDetailResponse,
    ObservabilityConversationListResponse,
    ObservabilityMetricsResponse,
    TraceDetailResponse,
    TraceListResponse,
)
from src.api.services.lab_agent_config_service import (
    LabAgentConfigService,
    LabAgentNotFoundError,
)
from src.api.services.lab_run_service import (
    LabModelInvocationError,
    LabRunService,
    UnsupportedLabModelError,
)
from src.api.services.observability_service import ObservabilityService
from src.observability.live_trace_store import live_trace_store

router = APIRouter(prefix="/observability", tags=["observability"])
EnvironmentFilter = Literal["development", "qa", "production"]
StatusFilter = Literal["completed", "error"]
ConversationStatusFilter = Literal["active", "ended"]


@router.get("/lab/models", response_model=LabModelCatalogResponse)
def list_lab_models() -> LabModelCatalogResponse:
    """Expose only the chat model currently accepted by the lab runner."""
    model_id = config.OPENAI_MODEL
    label = "GPT-6 Luna" if model_id == "gpt-6-luna" else model_id
    return LabModelCatalogResponse(
        models=[LabModelOptionResponse(model_id=model_id, label=label)],
        default_model_id=model_id,
    )


@router.post("/lab/run", response_model=LabRunResponse)
def run_lab_model(
    request: LabRunRequest,
    service: Annotated[LabRunService, Depends(get_lab_run_service)],
) -> LabRunResponse:
    try:
        return LabRunResponse(result=service.run(request))
    except UnsupportedLabModelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LabModelInvocationError as exc:
        raise HTTPException(
            status_code=502,
            detail="Não foi possível obter uma resposta do modelo.",
        ) from exc


@router.get("/agents/{agent_id}", response_model=LabAgentConfigResponse)
def get_lab_agent_config(
    agent_id: Annotated[str, Path(min_length=1)],
    service: Annotated[
        LabAgentConfigService,
        Depends(get_lab_agent_config_service),
    ],
) -> LabAgentConfigResponse:
    try:
        return service.get_agent_config(agent_id)
    except LabAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Agente não encontrado.") from exc


@router.get(
    "/conversations",
    response_model=ObservabilityConversationListResponse,
)
def list_conversations(
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    consumer_id: Annotated[
        str | None,
        Query(min_length=1, description="Email usado apenas para filtrar conversas."),
    ] = None,
    conversation_id: Annotated[str | None, Query(min_length=1)] = None,
    status: ConversationStatusFilter | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ObservabilityConversationListResponse:
    try:
        result = service.list_conversations(
            updated_from=updated_from,
            updated_to=updated_to,
            consumer_id=consumer_id,
            conversation_id=conversation_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return ObservabilityConversationListResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/conversations/{conversation_id}",
    response_model=ObservabilityConversationDetailResponse,
)
def get_conversation(
    conversation_id: Annotated[str, Path(min_length=1)],
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ObservabilityConversationDetailResponse:
    conversation = service.get_conversation(
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversa não encontrada.")
    return ObservabilityConversationDetailResponse.model_validate(conversation)


@router.get("/metrics", response_model=ObservabilityMetricsResponse)
def get_metrics(
    started_from: datetime,
    started_to: datetime,
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
    environment: EnvironmentFilter | None = None,
    status: StatusFilter | None = None,
    conversation_id: Annotated[str | None, Query(min_length=1)] = None,
    consumer_id: Annotated[
        str | None,
        Query(min_length=1, description="Email do usuário associado à conversa."),
    ] = None,
) -> ObservabilityMetricsResponse:
    try:
        result = service.calculate_metrics(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            consumer_id=consumer_id,
            environment=environment,
            status=status,
        )
        return cast(
            ObservabilityMetricsResponse,
            ObservabilityMetricsResponse.model_validate(result),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/traces", response_model=TraceListResponse)
def list_traces(
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    environment: EnvironmentFilter | None = None,
    status: StatusFilter | None = None,
    conversation_id: Annotated[str | None, Query(min_length=1)] = None,
    consumer_id: Annotated[
        str | None,
        Query(min_length=1, description="Email do usuário associado à conversa."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> TraceListResponse:
    try:
        result = service.list_traces(
            started_from=started_from,
            started_to=started_to,
            conversation_id=conversation_id,
            consumer_id=consumer_id,
            environment=environment,
            status=status,
            limit=limit,
            offset=offset,
        )
        return cast(TraceListResponse, TraceListResponse.model_validate(result))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/traces/live", response_model=LiveTraceFeedResponse)
def get_live_trace_feed(
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1_000)] = 500,
) -> LiveTraceFeedResponse:
    """Return recent events from traces that are executing in this API process."""
    return LiveTraceFeedResponse.model_validate(
        live_trace_store.get_feed(after=after, limit=limit)
    )


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
def get_trace(
    trace_id: Annotated[str, Path(min_length=1)],
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
) -> TraceDetailResponse:
    trace = service.get_trace(trace_id=trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace não encontrado.")
    return cast(TraceDetailResponse, TraceDetailResponse.model_validate(trace))
