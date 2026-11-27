"""AI notes on a new report's photos (roadmap 12.7, "cek foto").

Runs as a job after the report is committed, never in the chat's path: a vision model looks at
each stored photo, with the form's question and the report's choice and number answers for
comparison (free text is left out: it can hold people's names), and
its note lands in `report_photos.ai_note` for reviewers. Photos still kept as a Telegram
reference, files that are not images, and photos already noted are skipped. A failure leaves
the note empty; the report itself is never touched.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.modules.ai import vision
from app.modules.forms import service as forms
from app.modules.forms.errors import FormNotFound, FormVersionNotFound
from app.modules.forms.schemas import FormDefinition
from app.modules.reports import repository
from app.modules.reports.models import Report
from app.modules.reports.service import display

logger = logging.getLogger(__name__)

# What a photo can confirm or contradict: a condition, a species, a value on a display.
_COMPARABLE_TYPES = ("single_choice", "multi_choice", "number")


def enabled() -> bool:
    return vision.get_photo_checker() is not None


async def check_report_photos(
    db: AsyncSession, workspace_id: uuid.UUID, report_id: uuid.UUID
) -> int:
    """Note every unchecked photo of the report; returns how many notes were written."""
    checker = vision.get_photo_checker()
    if checker is None:
        return 0
    report = await db.get(Report, report_id)
    if report is None or report.workspace_id != workspace_id:
        return 0
    photos = [
        p
        for p in await repository.list_photos(db, report_id)
        if p.ai_note is None and not p.object_key.startswith("telegram:")
    ]
    if not photos:
        return 0
    try:
        form = await forms.get_form(db, workspace_id, report.form_id)
        version = await forms.get_version_definition(db, workspace_id, report.form_version_id)
    except FormNotFound, FormVersionNotFound:
        return 0
    definition = version.definition
    answers = _comparable_answers(definition, report.answers or {})
    written = 0
    for photo in photos:
        field = definition.field(photo.field_key)
        try:
            data = await get_storage().get(photo.object_key)
        except Exception:  # a missing or unreadable file: nothing to look at
            logger.warning("photo %s not readable for its check", photo.id, exc_info=True)
            continue
        content_type = vision.image_type(data)
        if content_type is None:
            continue
        context = vision.PhotoContext(
            form_name=form.name,
            field_label=field.label if field else photo.field_key,
            field_question=field.question if field else "",
            answers=answers,
            form_description=form.description,
        )
        note = await checker.check(data, content_type, context)
        if note:
            photo.ai_note = note
            written += 1
    await db.commit()
    return written


def _comparable_answers(definition: FormDefinition, answers: dict[str, object]) -> list[str]:
    """ "Kondisi tanaman: Terserang", "pH: 6,8" for each answered choice or number field."""
    shown = []
    for f in definition.fields:
        value = answers.get(f.key)
        if f.type in _COMPARABLE_TYPES and value not in (None, [], ""):
            shown.append(f"{f.label}: {display(f, value)}")
    return shown
