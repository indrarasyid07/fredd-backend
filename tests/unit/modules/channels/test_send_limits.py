"""Fair sending on the shared bots (roadmap 7.3). Real Redis (db 15), the test clock."""

import uuid

import pytest

from app.modules.channels import send_limits
from tests.conftest import SendClock


async def test_one_send_a_second_per_chat(send_clock: SendClock) -> None:
    assert await send_limits.wait_for_slot("telegram", "111", proactive=False) == 0
    waited = await send_limits.wait_for_slot("telegram", "111", proactive=False)
    assert 0 < waited <= 1.0  # the next second
    # Another chat is not held up.
    assert await send_limits.wait_for_slot("telegram", "222", proactive=False) == 0


async def test_replies_keep_room_that_reminders_cannot_use(
    send_clock: SendClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(send_limits, "BOT_PER_SECOND", 3)
    monkeypatch.setattr(send_limits, "PROACTIVE_PER_SECOND", 2)
    send_clock.now = float(int(send_clock.now)) + 0.1  # start of a second
    for chat in ("1", "2"):
        assert await send_limits.wait_for_slot("telegram", chat, proactive=True) == 0
    # A third reminder in the same second waits...
    assert await send_limits.wait_for_slot("telegram", "3", proactive=True) > 0
    send_clock.now = float(int(send_clock.now)) + 1.1  # a fresh second
    for chat in ("4", "5"):
        await send_limits.wait_for_slot("telegram", chat, proactive=True)
    # ...but a reply still fits in the second the reminders filled.
    assert await send_limits.wait_for_slot("telegram", "6", proactive=False) == 0
    assert await send_limits.wait_for_slot("telegram", "7", proactive=False) > 0  # bot full


async def test_each_organization_has_its_own_reminder_budget(
    send_clock: SendClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(send_limits, "PROACTIVE_PER_MINUTE", 2)
    send_clock.now = float(int(send_clock.now // 60) * 60) + 1  # start of a minute
    busy, other = uuid.uuid4(), uuid.uuid4()
    assert [await send_limits.take_budget(busy) for _ in range(3)] == [True, True, False]
    assert await send_limits.take_budget(other) is True
    send_clock.now += 60
    assert await send_limits.take_budget(busy) is True  # a new minute


async def test_waiting_has_a_limit(send_clock: SendClock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(send_limits, "MAX_WAIT_SECONDS", 2.0)

    async def stuck(seconds: float) -> None:  # time does not move on: the chat stays full
        send_clock.slept.append(seconds)

    monkeypatch.setattr(send_limits, "_sleep", stuck)
    await send_limits.wait_for_slot("telegram", "9", proactive=False)
    assert await send_limits.wait_for_slot("telegram", "9", proactive=False) >= 2.0
