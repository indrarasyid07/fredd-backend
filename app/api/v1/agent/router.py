"""Pengaturan agent: the organization's agent settings, a preview, and a test chat."""

from fastapi import APIRouter

from app.api.deps import DB, AdminMember, ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.agent import service
from app.modules.agent.schemas import (
    AgentPreviewOut,
    AgentSettings,
    AgentSettingsOut,
    AgentTestIn,
    AgentTestOut,
)

router = APIRouter()

_ERR = {"model": ApiErrorResponse}


@router.get(
    "/settings",
    response_model=ApiResponse[AgentSettingsOut],
    responses={401: _ERR, 403: _ERR},
)
async def get_settings(member: ReviewerMember, db: DB):
    """How the agent speaks to this organization's extension workers."""
    return ok(await service.get_settings_out(db, member.workspace_id))


@router.put(
    "/settings",
    response_model=ApiResponse[AgentSettingsOut],
    responses={401: _ERR, 403: _ERR, 422: _ERR},
)
async def update_settings(data: AgentSettings, member: AdminMember, db: DB):
    """Save the settings; the bot uses them from the next message. Admin only."""
    return ok(await service.update_settings(db, member, data))


@router.post(
    "/preview",
    response_model=ApiResponse[AgentPreviewOut],
    responses={401: _ERR, 403: _ERR, 422: _ERR},
)
async def preview(data: AgentSettings, member: ReviewerMember):
    """The greeting, report opening and closing lines these settings produce. Nothing is saved."""
    del member
    return ok(service.preview(data))


@router.post(
    "/test",
    response_model=ApiResponse[AgentTestOut],
    responses={401: _ERR, 403: _ERR, 404: _ERR, 409: _ERR, 422: _ERR},
)
async def test_chat(data: AgentTestIn, member: AdminMember, db: DB):
    """Replay a test chat with these settings on one data structure. Nothing is stored or sent
    to extension workers; answers the rules cannot read may go to the language model."""
    return ok(await service.run_test(db, member.workspace_id, data))
