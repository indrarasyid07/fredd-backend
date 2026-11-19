"""The conversation engine end to end, without a database or a channel (roadmap 3.3)."""

import pytest

from app.modules.conversations.engine import copy
from app.modules.conversations.engine.machine import extract_join_code, handle
from app.modules.conversations.engine.simulator import SimTopic, Simulator
from app.modules.conversations.engine.types import ConversationState, EngineContext, Inbound
from app.modules.forms.schemas import FormDefinition
from tests.form_definitions import crop_survey

CODE = "K7M29QXA"


def _topic(
    topic_id: str = "t1", label: str = "Dinas Pertanian · Survei", code: str = CODE
) -> SimTopic:
    return SimTopic(topic_id, label, FormDefinition.model_validate(crop_survey()), code)


@pytest.fixture
def sim() -> Simulator:
    return Simulator(topics=[_topic()])


def _join_and_answer_to_condition(sim: Simulator) -> None:
    sim.say("GABUNG K7M2-9QXA")
    sim.share_location(-6.9, 107.6, 8)
    sim.say("Pak Slamet")
    sim.say("1,5")


# --- Joining ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("K7M2-9QXA", CODE),
        ("k7m29qxa", CODE),
        ("gabung K7M2 9QXA", CODE),
        ("kode k7m2-9qxa", CODE),
        ("/start K7M29QXA", CODE),
        ("halo", None),
        ("K7M2-9QX", None),
        ("IIII-1111", None),  # look-alike characters are not in codes
    ],
)
def test_extract_join_code(text: str, code: str | None) -> None:
    assert extract_join_code(text) == code


def test_unbound_chat_only_gets_join_instructions(sim: Simulator) -> None:
    replies = sim.say("halo, saya mau lapor")
    assert [r.text for r in replies] == [copy.JOIN_FIRST]
    assert sim.reports == [] and sim.state.status == "idle"


def test_unknown_code_does_not_bind(sim: Simulator) -> None:
    sim.say("ABCD-EFGH")
    assert sim.bound == [] and sim.state.status == "idle"


# --- Full report --------------------------------------------------------------------------------


def test_full_report(sim: Simulator) -> None:
    first = sim.say("GABUNG K7M2-9QXA")
    assert first[0].text.startswith("Halo Pak Budi! Laporan *Dinas Pertanian · Survei*.")
    assert "1/5 Di mana lahan" in first[0].text and first[0].ask_location

    assert sim.share_location(-6.9, 107.6, 8)[0].text.startswith("2/5 Siapa nama petani")
    assert sim.say("Pak Slamet")[0].text.startswith("3/5 Berapa luas")

    # Number in words: confirm what was understood.
    confirm = sim.say("satu setengah hektar")
    assert confirm[0].text == "Dicatat *1,5 ha*. Benar?"
    question = sim.tap("yes")[0]
    assert question.text.startswith("4/5 Bagaimana kondisi")
    assert [b.label for b in question.buttons] == ["Sehat", "Perlu perhatian", "Terserang"]

    # "Terserang" makes the optional photos required (rule) — no skip offered.
    photos = sim.say("terserang hama")[0]
    assert photos.text.startswith("5/5 Boleh kirim") and copy.OPTIONAL_HINT not in photos.text
    received = sim.send_media("photo", "media/1.jpg")[0]
    assert received.text.startswith("Foto ke-1 diterima") and received.buttons[0].value == "done"

    summary = sim.tap("done")[0]
    assert summary.text.startswith("Ringkasan laporan:")
    assert "• Luas lahan: *1,5 ha*" in summary.text and "• Foto lahan: *1 foto*" in summary.text
    assert [b.value for b in summary.buttons] == ["submit", "edit"]

    saved = sim.tap("submit")
    assert saved[-1].text == "Laporan *LP-2611-0001* tersimpan. Terima kasih, Pak Budi."
    [report] = sim.reports
    assert report["answers"] == {
        "location": {"lat": -6.9, "lng": 107.6, "accuracy_m": 8},
        "farmer_name": "Pak Slamet",
        "land_area": "1.5",
        "condition": "infected",
        "photos": ["media/1.jpg"],
    }
    assert report["needs_review"] is False and sim.state.status == "submitted"


def test_progress_and_one_question_per_message(sim: Simulator) -> None:
    sim.say(CODE)
    for message in sim.channel.sent:
        assert message.text.count("?") <= 1


def test_optional_photos_can_be_skipped_when_healthy(sim: Simulator) -> None:
    _join_and_answer_to_condition(sim)
    photos = sim.tap("opt:healthy")[0]
    assert copy.OPTIONAL_HINT in photos.text and photos.buttons[-1].value == "skip"
    summary = sim.tap("skip")[0]
    assert "• Foto lahan: *-*" in summary.text
    sim.tap("submit")
    assert sim.reports[0]["answers"]["photos"] is None


def test_required_field_cannot_be_skipped(sim: Simulator) -> None:
    sim.say(CODE)
    replies = sim.say("lewati")
    assert replies[0].text == copy.REQUIRED and sim.state.step == "location"


# --- Wrong answers ------------------------------------------------------------------------------


def test_wrong_number_explains_with_an_example(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    sim.say("Pak Slamet")
    replies = sim.say("banyak")
    assert replies[0].text == copy.NOT_A_NUMBER and replies[1].text.startswith("3/5")
    assert sim.say("900")[0].text == "Angka harus antara 0 dan 500 ha."
    assert sim.say("2 kg")[0].text.startswith("Tulis dalam ha")


def test_three_failures_offer_help(sim: Simulator) -> None:
    _join_and_answer_to_condition(sim)
    sim.say("entahlah")
    sim.say("tidak tahu")
    replies = sim.say("hmm")
    assert replies[-1].text == copy.THREE_FAILS
    assert [b.value for b in replies[-1].buttons] == ["help"]  # condition is required: no skip

    help_reply = sim.tap("help")
    assert help_reply[0].text == copy.HELP_SENT
    assert sim.state.status == "needs_help"
    assert [(h.reason, h.field) for h in sim.help_requests] == [("asked_for_help", "condition")]
    assert sim.say("halo?") == []  # waiting for the admin: the bot stays quiet


def test_inaccurate_location_is_asked_again(sim: Simulator) -> None:
    sim.say(CODE)
    replies = sim.share_location(-6.9, 107.6, 400)
    assert replies[0].text.startswith("Lokasi kurang akurat (lebih dari 50 m)")
    assert sim.state.step == "location"


def test_typo_in_a_choice_is_confirmed(sim: Simulator) -> None:
    _join_and_answer_to_condition(sim)
    ask = sim.say("sehta")[0]
    assert ask.text == "Maksud Anda *Sehat*?"
    again = sim.tap("no")[0]
    assert again.text.startswith("4/5") and "condition" not in sim.state.answers
    sim.say("sehta")
    sim.tap("yes")
    assert sim.state.answers["condition"] == "healthy"


def test_voice_note_for_a_text_question(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    assert sim.send_media("voice", "media/v.ogg")[0].text == copy.VOICE_LATER


# --- Review, editing, resuming ------------------------------------------------------------------


def test_large_area_goes_to_review(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    sim.say("Pak Slamet")
    sim.say("60 ha")
    sim.tap("opt:healthy")
    sim.tap("skip")
    sim.tap("submit")
    assert sim.reports[0]["needs_review"] is True
    assert sim.reports[0]["review_reasons"] == ("review_above:land_area",)


def test_rule_needs_review_on_zero_area(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    sim.say("Pak Slamet")
    sim.say("0")
    sim.tap("opt:healthy")
    sim.tap("skip")
    sim.tap("submit")
    assert sim.reports[0]["review_reasons"] == ("rule:1",)


def test_edit_an_answer_from_the_summary(sim: Simulator) -> None:
    _join_and_answer_to_condition(sim)
    sim.tap("opt:healthy")
    sim.tap("skip")
    which = sim.tap("edit")[0]
    assert [b.value for b in which.buttons][:2] == ["edit:location", "edit:farmer_name"]
    question = sim.tap("edit:farmer_name")[0]
    assert "Siapa nama petani" in question.text
    summary = sim.say("Bu Ani")[0]
    assert summary.text.startswith("Ringkasan") and "*Bu Ani*" in summary.text
    sim.tap("submit")
    assert sim.reports[0]["answers"]["farmer_name"] == "Bu Ani"


def test_changing_condition_back_drops_the_rule(sim: Simulator) -> None:
    _join_and_answer_to_condition(sim)
    sim.say("terserang")
    sim.send_media("photo", "media/1.jpg")
    sim.tap("done")
    sim.tap("edit")
    sim.tap("edit:condition")
    sim.tap("opt:healthy")
    assert sim.state.required_by_rules == [] and sim.state.status == "confirming_summary"


def test_resume_and_restart(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    assert sim.say("lanjut")[0].text.startswith("2/5")
    restarted = sim.say("mulai ulang")[0]
    assert "1/5" in restarted.text and sim.state.answers == {}


def test_new_report_after_submitting(sim: Simulator) -> None:
    _join_and_answer_to_condition(sim)
    sim.tap("opt:healthy")
    sim.tap("skip")
    sim.tap("submit")
    again = sim.say("mulai")[0]
    assert "1/5" in again.text and sim.state.answers == {}


# --- Several topics, takeover, persistence ------------------------------------------------------


def test_worker_with_two_topics_chooses(sim: Simulator) -> None:
    sim.topics.append(_topic("t2", "Dinas Pertanian · Panen", "R4H8T2NW"))
    sim.say(CODE)
    sim.say("R4H8-T2NW")  # joins a second topic and starts it
    sim.say("mulai ulang")
    assert sim.state.topic_id == "t2"
    sim.state.status = "submitted"
    choose = sim.say("mulai")[0]
    assert choose.text == copy.CHOOSE_TOPIC and len(choose.buttons) == 2
    started = sim.tap("topic:t1")[0]
    assert "Survei" in started.text and sim.state.topic_id == "t1"


def test_takeover_keeps_the_bot_silent(sim: Simulator) -> None:
    sim.say(CODE)
    sim.state.status = "taken_over"
    assert sim.say("halo admin") == []
    assert sim.state.status == "taken_over"


def test_state_survives_json() -> None:
    state = ConversationState(status="asking", topic_id="t1", step="land_area", answers={"a": "1"})
    assert ConversationState.from_json(state.to_json()) == state
    assert ConversationState.from_json({"status": "idle", "unknown_key": 1}).status == "idle"


def test_handle_does_not_mutate_the_given_state() -> None:
    state = ConversationState(status="idle")
    ctx = EngineContext(salutation="Kak", today=Simulator(topics=[]).today)
    handle(state, Inbound(text="K7M2-9QXA"), ctx)
    assert state.status == "idle"


def test_unknown_code_mid_report_keeps_the_progress(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    replies = sim.say("ZZZZ-ZZZZ")
    assert replies[0].text == "Kode tidak dikenali."
    assert (sim.state.status, sim.state.step) == ("asking", "farmer_name")
    assert "location" in sim.state.answers


def test_bare_letters_mid_report_are_an_answer(sim: Simulator) -> None:
    sim.say(CODE)
    sim.share_location(-6.9, 107.6, 8)
    sim.say("BAMBANGS")  # eight code-like letters: a name here, not a join code
    assert sim.state.answers["farmer_name"] == "BAMBANGS"
