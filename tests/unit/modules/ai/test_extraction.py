"""Reading lab values out of one spoken sentence (roadmap 12.1): cues, units, confidence."""

from typing import Any

import pytest

from app.modules.ai import speech
from app.modules.ai.extraction import CONFIDENT, extract, read_value
from app.modules.forms.schemas import FormDefinition

LAB = FormDefinition.model_validate(
    {
        "fields": [
            {"key": "sample", "type": "short_text", "label": "Nomor sampel", "question": "?"},
            {"key": "ph", "type": "number", "label": "pH", "question": "?", "role": "measure"},
            {"key": "temp", "type": "number", "label": "Suhu", "question": "?", "unit": "°C",
             "min": -20, "max": 120, "role": "measure"},
            {"key": "room_temp", "type": "number", "label": "Suhu ruang", "question": "?",
             "unit": "°C", "required": False},
            {"key": "volume", "type": "number", "label": "Volume", "question": "?", "unit": "mL"},
            {"key": "status", "type": "single_choice", "label": "Status", "question": "?",
             "options": [{"value": "ok", "label": "Lolos"}, {"value": "fail", "label": "Gagal"}]},
            {"key": "tests", "type": "multi_choice", "label": "Uji", "question": "?",
             "required": False,
             "options": [{"value": "micro", "label": "Mikroba"},
                         {"value": "metal", "label": "Logam"}]},
        ],
        "rules": [],
    }
)  # fmt: skip
CUES = {"sample": ["sampel"]}


def _values(text: str) -> dict[str, tuple[Any, float]]:
    result = extract(text, LAB, cues=CUES)
    return {v.field_key: (v.value, v.confidence) for v in result.values}


def test_one_sentence_fills_every_field() -> None:
    result = extract(
        "Sampel S-2041, pH 6,8, suhu 25 derajat, volume 50 mililiter, status lolos",
        LAB,
        cues=CUES,
    )
    got = {v.field_key: (v.value, v.display) for v in result.values}
    assert got == {
        "sample": ("S-2041", "S-2041"),
        "ph": ("6.8", "6,8"),
        "temp": ("25", "25 °C"),
        "volume": ("50", "50 mL"),
        "status": ("ok", "Lolos"),
    }
    assert result.unsure == [] and result.missing == []
    assert result.value("temp").heard == "25 derajat"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("said", "key", "value", "sure"),
    [
        ("volume 50 ml pH 7.2", "ph", "7.2", True),  # any order, dot decimal
        ("pH-nya adalah 6,8", "ph", "6.8", True),  # filler words
        ("suhu: 30 °C", "temp", "30", True),
        ("suhu 25 ml", "temp", "25", False),  # wrong unit heard
        ("suhu 500 derajat", "temp", "500", False),  # outside the field's bounds
        ("pH asam", "ph", None, False),  # not a number
        ("status gagal", "status", "fail", True),
        ("status entah", "status", None, False),
        ("uji mikroba dan logam", "tests", ["micro", "metal"], True),
    ],
)
def test_values_and_confidence(said: str, key: str, value: Any, sure: bool) -> None:
    got_value, confidence = _values(said)[key]
    assert got_value == value
    assert (confidence >= CONFIDENT) is sure


def test_longer_cue_wins_over_the_shorter_inside_it() -> None:
    got = _values("suhu ruang 22 derajat, suhu 30 derajat")
    assert got["room_temp"][0] == "22" and got["temp"][0] == "30"


def test_required_fields_not_said_are_missing() -> None:
    result = extract("pH 7", LAB, cues=CUES)
    assert result.missing == ["sample", "temp", "volume", "status"]


def test_nothing_recognised() -> None:
    result = extract("selamat pagi semuanya", LAB, cues=CUES)
    assert result.values == [] and "ph" in result.missing


async def test_fake_speech_reads_the_audio_as_text() -> None:
    stt = speech.get_speech_to_text()
    transcript = await stt.transcribe(b"pH 6,8 ", "audio/ogg")
    assert (transcript.text, transcript.provider, transcript.language) == ("pH 6,8", "fake", "id")


def test_unknown_provider_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(speech.settings, "stt_provider", "nowhere")
    with pytest.raises(speech.SpeechUnavailable):
        speech.get_speech_to_text()


def test_short_text_that_ran_on_is_doubtful() -> None:
    lab = FormDefinition.model_validate(
        {
            "fields": [
                {"key": "sample", "type": "short_text", "label": "Nomor sampel",
                 "question": "?", "voice_cues": ["kode"]},
                {"key": "ph", "type": "number", "label": "pH", "question": "?"},
            ]
        }
    )  # fmt: skip
    ran_on = extract("kode S-9 asamnya netral tujuh, panasnya dua lima derajat", lab)
    value = ran_on.value("sample")
    assert value is not None and value.confidence < CONFIDENT and value.doubt
    clean = extract("kode S-9, pH 7", lab).value("sample")
    assert clean is not None and clean.value == "S-9" and clean.confidence >= CONFIDENT


def test_minus_sign_is_kept() -> None:
    freezer = FormDefinition.model_validate(
        {"fields": [{"key": "temp", "type": "number", "label": "Suhu", "question": "?",
                     "unit": "°C", "unit_aliases": ["derajat"]}]}
    )  # fmt: skip
    value = extract("suhu -20 derajat", freezer).value("temp")
    assert value is not None and value.value == "-20"
    word = extract("suhu-nya 4 derajat", freezer).value("temp")  # "-nya" is not a sign
    assert word is not None and word.value == "4"
    read = read_value(freezer.fields[0], "-5")
    assert read is not None and read.value == "-5"
