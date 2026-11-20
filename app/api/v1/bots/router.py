"""The platform's shared bots (B-048): what admins share with their extension workers."""

from fastapi import APIRouter

from app.api.deps import ReviewerMember
from app.api.responses import ApiErrorResponse, ApiResponse, ok
from app.modules.channels import service
from app.modules.channels.schemas import BotOut

router = APIRouter()

_ERR = {"model": ApiErrorResponse}


@router.get("", response_model=ApiResponse[list[BotOut]], responses={401: _ERR, 403: _ERR})
async def list_bots(member: ReviewerMember):
    del member  # any member of the workspace may see them
    return ok(service.list_bots())
