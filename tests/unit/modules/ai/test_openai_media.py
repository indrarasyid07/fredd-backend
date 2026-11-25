"""OpenAI speech to text and photo checks (roadmap 12.7): what is sent, what comes back, and
that a failing check means "no note" rather than an error."""

import json
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest

from app.modules.ai import openai_client, speech, vision
from app.modules.ai.speech import OpenAISpeechToText
from app.modules.ai.vision import OpenAIPhotoChecker, PhotoContext, as_note, describe, image_type

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
CONTEXT = PhotoContext(
    form_name="Survei Kondisi Tanaman",
    field_label="Foto lahan",
    field_question="Boleh kirim 1 sampai 3 foto lahannya?",
    answers=("Kondisi tanaman: Terserang",),
)


class _Recorder:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# --- Speech to text -----------------------------------------------------------------------------


async def test_transcribes_a_voice_note_in_indonesian() -> None:
    recorder = _Recorder(SimpleNamespace(text=" Satu koma lima hektar. "))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=recorder))
    stt = OpenAISpeechToText(client, "gpt-4o-mini-transcribe")  # type: ignore[arg-type]
    transcript = await stt.transcribe(b"OggS\x00audio", "audio/ogg")
    assert transcript.text == "Satu koma lima hektar."
    assert transcript.provider == "openai" and transcript.language == "id"
    sent = recorder.calls[0]
    assert sent["model"] == "gpt-4o-mini-transcribe"
    assert sent["file"] == ("voice.ogg", b"OggS\x00audio", "audio/ogg")
    assert sent["language"] == "id"


def test_fake_provider_only_transcribes_voice_lab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "override", None)
    monkeypatch.setattr(speech.settings, "stt_provider", "fake")
    assert speech.transcribes_every_voice_note() is False


def test_openai_provider_transcribes_every_voice_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech, "override", None)
    monkeypatch.setattr(speech.settings, "stt_provider", "openai")
    monkeypatch.setattr(openai_client.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(openai_client, "_client", None)
    assert speech.transcribes_every_voice_note() is True
    assert isinstance(speech.get_speech_to_text(), OpenAISpeechToText)
    monkeypatch.setattr(openai_client.settings, "openai_api_key", "")
    assert speech.transcribes_every_voice_note() is False
    with pytest.raises(speech.SpeechUnavailable):
        speech.get_speech_to_text()


# --- Photo checks -------------------------------------------------------------------------------


def _checker(result: Any) -> tuple[OpenAIPhotoChecker, _Recorder]:
    recorder = _Recorder(result)
    client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
    return OpenAIPhotoChecker(client, "gpt-5.4-mini", "low"), recorder  # type: ignore[arg-type]


def _response(content: dict[str, Any], finish_reason: str = "stop") -> SimpleNamespace:
    message = SimpleNamespace(content=json.dumps(content), refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish_reason, message=message)])


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (JPEG, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"%PDF-1.7", None),
    ],
)
def test_image_type(data: bytes, content_type: str | None) -> None:
    assert image_type(data) == content_type


@pytest.mark.parametrize(
    ("result", "note"),
    [
        ({"note": "Daun padi menguning.", "issue": "none"}, "Daun padi menguning."),
        ({"note": "Foto kabur.", "issue": "blurry"}, "Perlu dicek (buram): Foto kabur."),
        (
            {"note": "Tanaman tampak sehat.", "issue": "mismatch"},
            "Perlu dicek (berbeda dengan laporan): Tanaman tampak sehat.",
        ),
        ({"note": "", "issue": "none"}, None),
        ({"note": "x", "issue": "weird"}, None),
        ("not a dict", None),
    ],
)
def test_as_note(result: Any, note: str | None) -> None:
    assert as_note(result) == note


def test_long_notes_fit_the_column() -> None:
    note = as_note({"note": "a" * 900, "issue": "other"})
    assert note is not None and len(note) == 500


def test_describe_fences_the_answers() -> None:
    text = describe(CONTEXT)
    assert "Question asked: Boleh kirim 1 sampai 3 foto lahannya?" in text
    assert text.endswith("<report_answers>\n- Kondisi tanaman: Terserang\n</report_answers>")


async def test_sends_the_photo_inline_at_low_detail() -> None:
    checker, recorder = _checker(_response({"note": "Daun berlubang.", "issue": "none"}))
    assert await checker.check(JPEG, "image/jpeg", CONTEXT) == "Daun berlubang."
    sent = recorder.calls[0]
    image = sent["messages"][1]["content"][1]["image_url"]
    assert image["url"].startswith("data:image/jpeg;base64,")
    assert image["detail"] == "low"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["reasoning_effort"] == "low"


async def test_failed_checks_write_no_note() -> None:
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    checker, _ = _checker(openai.APIConnectionError(request=request))
    assert await checker.check(JPEG, "image/jpeg", CONTEXT) is None
    checker, _ = _checker(_response({"note": "x", "issue": "none"}, finish_reason="length"))
    assert await checker.check(JPEG, "image/jpeg", CONTEXT) is None


def test_photo_checks_follow_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "override", None)
    monkeypatch.setattr(openai_client.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(openai_client, "_client", None)
    monkeypatch.setattr(vision.settings, "llm_provider", "off")
    assert vision.get_photo_checker() is None
    monkeypatch.setattr(vision.settings, "llm_provider", "openai")
    assert isinstance(vision.get_photo_checker(), OpenAIPhotoChecker)
