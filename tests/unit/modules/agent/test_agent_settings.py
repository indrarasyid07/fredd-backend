"""Pengaturan agent: the defaults keep the bot's original wording, the styles change only the
opening and closing lines, and the settings are validated before they reach the bot."""

import pytest
from pydantic import ValidationError

from app.modules.agent.schemas import AgentSettings
from app.modules.agent.service import preview, voice_of
from app.modules.conversations.engine import copy
from app.modules.conversations.engine.simulator import SimTopic, Simulator
from app.modules.conversations.engine.types import AgentVoice
from app.modules.forms.schemas import FormDefinition
from tests.form_definitions import crop_survey


def test_defaults_keep_the_original_wording() -> None:
    assert copy.AFTER_KEEP == (
        "Siap. Saya Fluctuz, asisten yang membantu mencatat laporan lapangan. "
        "Ketik *mulai* untuk melapor."
    )
    assert copy.AFTER_KEEP_VOICE == (
        "Siap. Saya Fluctuz, asisten yang mencatat hasil kerja Anda. "
        "Kirim *pesan suara* berisi hasilnya, atau ketik *mulai*."
    )
    assert (
        copy.greet("Budi", "Survei", "1/5 Lokasi?") == "Halo Budi! Laporan *Survei*.\n\n1/5 Lokasi?"
    )
    assert copy.report_saved("LP-1", "Budi") == "Laporan *LP-1* tersimpan. Terima kasih, Budi."
    assert voice_of(AgentSettings()) == AgentVoice()


@pytest.mark.parametrize(
    ("style", "start", "saved"),
    [
        ("friendly", "Halo Budi! Laporan *S*.", "Laporan *LP-1* tersimpan. Terima kasih, Budi."),
        (
            "formal",
            "Selamat datang, Budi. Berikut laporan *S*.",
            "Laporan *LP-1* telah tersimpan. Terima kasih atas laporan Anda, Budi.",
        ),
        ("brief", "Laporan *S*.", "Tersimpan: *LP-1*."),
    ],
)
def test_styles(style: str, start: str, saved: str) -> None:
    assert copy.greet("Budi", "S", "Q", style).startswith(start)  # type: ignore[arg-type]
    assert copy.report_saved("LP-1", "Budi", style) == saved  # type: ignore[arg-type]


def test_custom_greeting_and_name() -> None:
    assert copy.after_keep("Tani Bot", "formal") == (
        "Terima kasih. Saya Tani Bot, asisten yang membantu mencatat laporan lapangan. "
        "Ketik *mulai* untuk melapor."
    )
    assert copy.after_keep("Tani Bot", "brief", "Halo, kirim laporan Anda.", voice_mode=True) == (
        "Halo, kirim laporan Anda. Kirim *pesan suara* berisi hasilnya, atau ketik *mulai*."
    )


def test_settings_are_cleaned_and_validated() -> None:
    s = AgentSettings(name="  Tani   Bot ", greeting="  Halo,\n kirim laporan.  ")
    assert s.name == "Tani Bot" and s.greeting == "Halo, kirim laporan."
    assert AgentSettings(greeting="   ").greeting is None
    with pytest.raises(ValidationError):
        AgentSettings(name="   ")
    with pytest.raises(ValidationError):
        AgentSettings(style="casual")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        AgentSettings.model_validate({"name": "x", "unknown": 1})


def test_preview_follows_the_settings() -> None:
    lines = preview(AgentSettings(name="Tani Bot", style="brief", greeting=None))
    assert lines.after_join.startswith("Siap, saya Tani Bot.")
    assert lines.report_start.startswith("Laporan *Survei Kondisi Tanaman*.")
    assert lines.report_saved == "Tersimpan: *LP-2611-0148*."


def test_engine_uses_the_agent_style() -> None:
    topic = SimTopic(
        "t1", "Dinas · Survei", FormDefinition.model_validate(crop_survey()), "K7M29QXA"
    )
    sim = Simulator(topics=[topic])
    sim.say("GABUNG K7M2-9QXA")
    # The simulator's context has the default voice: the original greeting.
    assert sim.channel.sent[-1].text.startswith("Halo ")
