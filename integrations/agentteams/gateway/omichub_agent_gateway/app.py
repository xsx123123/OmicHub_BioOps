"""REST application for the read-only scientific-interpretation Skill."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from .audit import AuditStore
from .client import OmicHubConsultationClient
from .config import GatewaySettings
from .matrix_client import MatrixGatewayClient
from .models import (
    ConsultationRequest,
    EnsureUsersRequest,
    RoomCreateRequest,
    RoomCreateResponse,
    RoomMessageRequest,
    RoomMessagesResponse,
    ScientificInterpretationResponse,
)
from .security import require_manager
from .service import GatewayService


async def get_service(request: Request) -> GatewayService:
    return request.app.state.gateway_service


async def authenticate_manager(
    request: Request,
    x_gateway_identity: str | None = Header(default=None),
    x_gateway_token: str | None = Header(default=None),
) -> str:
    return require_manager(request.app.state.gateway_settings, x_gateway_identity, x_gateway_token)


def create_app(
    settings: GatewaySettings | None = None,
    client: OmicHubConsultationClient | None = None,
    matrix_client: MatrixGatewayClient | None = None,
) -> FastAPI:
    runtime_settings = settings or GatewaySettings()
    runtime_client = client or OmicHubConsultationClient(runtime_settings)
    runtime_matrix_client = matrix_client or (
        MatrixGatewayClient(runtime_settings) if runtime_settings.matrix_enabled else None
    )
    service = GatewayService(
        runtime_settings,
        runtime_client,
        AuditStore(runtime_settings.audit_log_path),
        runtime_matrix_client,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if runtime_settings.omichub_integration_token:
            try:
                runtime_settings.apply_capability_snapshot(await runtime_client.capabilities())
            except Exception:
                if runtime_settings.environment == "production":
                    raise
        yield
        await runtime_client.close()
        await service.aclose()
        if runtime_matrix_client is not None:
            await runtime_matrix_client.close()

    app = FastAPI(
        title="OmicHub Controlled Agent Gateway",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.gateway_settings = runtime_settings
    app.state.gateway_service = service

    @app.get("/healthz", tags=["Health"])
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "matrix": {
                "configured": runtime_settings.matrix_enabled,
                "identity_count": len(runtime_settings.matrix_identity_map()),
            },
        }

    @app.post(
        "/v1/scientific-interpretation",
        response_model=ScientificInterpretationResponse,
        tags=["Skills"],
    )
    async def scientific_interpretation(
        payload: ConsultationRequest,
        actor: Annotated[str, Depends(authenticate_manager)],
        gateway_service: Annotated[GatewayService, Depends(get_service)],
    ) -> ScientificInterpretationResponse:
        return await gateway_service.consult(payload, actor)

    @app.post("/rooms", response_model=RoomCreateResponse, tags=["Matrix"])
    async def create_room(
        payload: RoomCreateRequest,
        actor: Annotated[str, Depends(authenticate_manager)],
        gateway_service: Annotated[GatewayService, Depends(get_service)],
    ) -> RoomCreateResponse:
        try:
            return await gateway_service.create_room(payload.session_id, payload.identities, actor)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/users/ensure", tags=["Matrix"])
    async def ensure_users(
        payload: EnsureUsersRequest,
        actor: Annotated[str, Depends(authenticate_manager)],
        gateway_service: Annotated[GatewayService, Depends(get_service)],
    ) -> dict[str, list[str]]:
        try:
            ensured = await gateway_service.ensure_users(payload.identities, actor)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ensured": ensured}

    @app.post("/rooms/{room_id}/messages", tags=["Matrix"])
    async def post_room_message(
        room_id: str,
        payload: RoomMessageRequest,
        actor: Annotated[str, Depends(authenticate_manager)],
        gateway_service: Annotated[GatewayService, Depends(get_service)],
    ) -> dict[str, str]:
        try:
            return {"event_id": await gateway_service.post_room_message(room_id, payload, actor)}
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/rooms/{room_id}/messages", response_model=RoomMessagesResponse, tags=["Matrix"])
    async def room_messages(
        room_id: str,
        since: str | None = None,
        limit: int = 100,
        _: Annotated[str, Depends(authenticate_manager)] = None,
        gateway_service: Annotated[GatewayService, Depends(get_service)] = None,
    ) -> RoomMessagesResponse:
        try:
            return await gateway_service.room_messages(room_id, since, min(max(limit, 1), 1000))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/rooms/{room_id}/sync", tags=["Matrix"])
    async def room_sync(
        room_id: str,
        since: str | None = None,
        _: Annotated[str, Depends(authenticate_manager)] = None,
        gateway_service: Annotated[GatewayService, Depends(get_service)] = None,
    ) -> StreamingResponse:
        async def event_stream():
            try:
                async for events, next_batch in gateway_service.room_sync(room_id, since):
                    for event in events:
                        yield f"data: {event.model_dump_json()}\n\n"
                    yield f"event: cursor\ndata: {json.dumps({'next_batch': next_batch})}\n\n"
            except RuntimeError as exc:
                yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_app()
