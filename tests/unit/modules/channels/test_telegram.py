"""Telegram adapter: update parsing (3.5a) and Bot API calls, without the network."""

import json

import httpx
import pytest

from app.modules.channels.telegram import (
    BotBlocked,
    InboundUpdate,
    LeaveGroup,
    TelegramClient,
    TelegramError,
    parse_update,
    render_html,
    reply_markup,
)
from app.modules.conversations.engine.types import Button, Outbound
from tests.telegram_fixtures import telegram_update


def _inbound(name: str) -> InboundUpdate:
    parsed = parse_update(telegram_update(name))
    assert isinstance(parsed, InboundUpdate)
    return parsed


def test_text_message() -> None:
    u = _inbound("text")
    assert (u.kind, u.chat_id, u.body, u.external_id) == (
        "text",
        "700100200",
        "halo",
        "update:510000001",
    )
    assert u.payload["user_id"] == "700100200"
    assert u.payload["name"] == "Budi Santoso"
    assert u.payload["username"] == "budi_tani"


def test_button_tap_carries_the_value_and_callback_id() -> None:
    u = _inbound("callback")
    assert (u.kind, u.body) == ("button", "opt:padi")
    assert u.payload["callback_id"] == "4382bfdwdsb323b2d9"


def test_photo_keeps_the_largest_size_and_caption() -> None:
    u = _inbound("photo")
    assert (u.kind, u.body, u.payload["file_id"]) == ("photo", "lahan blok A", "AgACAgUAAxk-large")


def test_album_photos_share_their_group() -> None:
    a, b = _inbound("album_1"), _inbound("album_2")
    assert a.payload["media_group_id"] == b.payload["media_group_id"] == "13579246801357924"


def test_location_and_live_location_start() -> None:
    u = _inbound("location")
    assert (u.payload["lat"], u.payload["lng"], u.payload["accuracy_m"]) == (-7.2167, 107.9, 12.5)
    assert _inbound("live_location").payload["live"] is True


def test_live_location_moves_are_ignored() -> None:
    assert parse_update(telegram_update("live_location_moved")) is None


def test_edited_text_is_flagged() -> None:
    u = _inbound("edited_text")
    assert (u.kind, u.payload["edited"]) == ("other", True)


def test_voice_and_sticker() -> None:
    assert _inbound("voice").kind == "voice"
    sticker = _inbound("sticker")
    assert (sticker.kind, sticker.payload["type"]) == ("other", "sticker")


def test_groups_are_ignored_and_left() -> None:
    assert parse_update(telegram_update("group_text")) is None
    assert parse_update(telegram_update("added_to_group")) == LeaveGroup("-1001234567890")


def test_blocking_the_bot() -> None:
    assert parse_update(telegram_update("blocked")) == BotBlocked("700100200")


@pytest.mark.parametrize(
    "update", [{}, {"update_id": "x"}, {"update_id": 1}, {"update_id": 1, "message": {}}]
)
def test_odd_updates_are_ignored(update: dict[str, object]) -> None:
    assert parse_update(update) is None


def test_html_escapes_and_bolds() -> None:
    assert render_html("Luas *1,5 ha* <ok> & beres") == "Luas <b>1,5 ha</b> &lt;ok&gt; &amp; beres"


def test_short_buttons_share_a_row_long_ones_stack() -> None:
    short = reply_markup(Outbound("?", buttons=(Button("Ya", "yes"), Button("Ubah", "no"))))
    assert short == {"inline_keyboard": [[{"text": "Ya", "callback_data": "yes"},
                                          {"text": "Ubah", "callback_data": "no"}]]}  # fmt: skip
    long = reply_markup(Outbound("?", buttons=(Button("Minta bantuan admin", "help"),)))
    assert long == {"inline_keyboard": [[{"text": "Minta bantuan admin", "callback_data": "help"}]]}


def test_callback_data_over_64_bytes_is_refused() -> None:
    with pytest.raises(ValueError):
        reply_markup(Outbound("?", buttons=(Button("x", "opt:" + "a" * 61),)))


def test_location_request_keyboard() -> None:
    markup = reply_markup(Outbound("Lokasi?", ask_location=True))
    assert markup is not None
    assert markup["keyboard"][0][0]["request_location"] is True


# --- Bot API calls ------------------------------------------------------------------------------

TOKEN = "123456:SECRET-TOKEN"


def _client(handler: httpx.MockTransport) -> TelegramClient:
    return TelegramClient(TOKEN, transport=handler)


async def test_send_posts_html_and_returns_the_message_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    client = _client(httpx.MockTransport(handler))
    assert await client.send("700100200", Outbound("Luas *2 ha*")) == "77"
    sent = json.loads(seen[0].content)
    assert seen[0].url.path == f"/bot{TOKEN}/sendMessage"
    assert sent == {"chat_id": "700100200", "text": "Luas <b>2 ha</b>", "parse_mode": "HTML"}


async def test_api_error_keeps_the_code_but_never_the_token() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "ok": False,
                "error_code": 403,
                "description": "Forbidden: bot was blocked by the user",
            },
        )

    with pytest.raises(TelegramError) as caught:
        await _client(httpx.MockTransport(handler)).send("1", Outbound("hai"))
    assert caught.value.status == 403
    assert TOKEN not in str(caught.value)


async def test_timeout_is_marked_as_such() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TelegramError) as caught:
        await _client(httpx.MockTransport(handler)).send("1", Outbound("hai"))
    assert caught.value.timed_out
    assert TOKEN not in str(caught.value)


def _file_server(content: bytes, announced: int | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            assert json.loads(request.content) == {"file_id": "F1"}
            size = announced if announced is not None else len(content)
            result = {"file_id": "F1", "file_path": "photos/file_1.jpg", "file_size": size}
            return httpx.Response(200, json={"ok": True, "result": result})
        assert request.url.path == f"/file/bot{TOKEN}/photos/file_1.jpg"
        return httpx.Response(200, content=content)

    return httpx.MockTransport(handler)


async def test_download_file_fetches_the_bytes() -> None:
    client = _client(_file_server(b"\xff\xd8\xff photo"))
    assert await client.download_file("F1", max_bytes=100) == b"\xff\xd8\xff photo"


@pytest.mark.parametrize("announced", [500, 0])
async def test_download_file_refuses_large_files(announced: int) -> None:
    # Refused from the announced size, or while reading when the size was not announced.
    client = _client(_file_server(b"x" * 500, announced=announced))
    with pytest.raises(TelegramError) as caught:
        await client.download_file("F1", max_bytes=100)
    assert caught.value.status == 413
