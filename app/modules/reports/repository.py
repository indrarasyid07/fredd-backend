import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.models import Report, ReportCodeCounter
from app.modules.workspaces.models import Workspace


async def get_timezone(db: AsyncSession, workspace_id: uuid.UUID) -> ZoneInfo:
    name = await db.scalar(select(Workspace.timezone).where(Workspace.id == workspace_id))
    return ZoneInfo(name or "Asia/Jakarta")


async def take_code_number(db: AsyncSession, workspace_id: uuid.UUID, period: str) -> int:
    """The next number for this workspace and month, atomically (row lock on the counter)."""
    result = await db.execute(
        insert(ReportCodeCounter)
        .values(workspace_id=workspace_id, period=period, last_value=1)
        .on_conflict_do_update(
            index_elements=["workspace_id", "period"],
            set_={"last_value": ReportCodeCounter.last_value + 1},
        )
        .returning(ReportCodeCounter.last_value)
    )
    return int(result.scalar_one())


async def get_report(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> Report | None:
    return await db.scalar(
        select(Report).where(Report.workspace_id == workspace_id, Report.id == report_id)
    )
