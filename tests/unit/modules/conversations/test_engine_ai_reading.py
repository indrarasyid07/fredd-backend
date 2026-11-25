"""A language model's reading of an unreadable answer (roadmap 12.7): only for answers the
parsers did not understand, checked with the same rules, and always confirmed."""

from app.modules.conversations.engine import copy
from app.modules.conversations.engine.machine import handle
from app.modules.conversations.engine.simulator import SimTopic, Simulator
from app.modules.conversations.engine.types import Inbound, Media, Step
from app.modules.forms.schemas import FormDefinition
from tests.form_definitions import crop_survey


def _at_land_area() -> Simulator:
    topic = SimTopic("t1", "Dinas Pertanian · Survei", FormDefinition.model_validate(crop_survey()),
                     "K7M29QXA")  # fmt: skip
    sim = Simulator(topics=[topic])
    sim.say("GABUNG K7M2-9QXA")
    sim.share_location(-6.9, 107.6, 8)
    sim.say("Pak Slamet")
    assert sim.state.step == "land_area"
    return sim


def _send(sim: Simulator, message: Inbound) -> Step:
    return handle(sim.state, message, sim._context())


def test_unreadable_number_is_marked_for_the_language_model() -> None:
    step = _send(_at_land_area(), Inbound(text="lumayan, sekitar segini lah"))
    assert step.unread == "land_area"
    assert step.replies[0].text == copy.NOT_A_NUMBER  # the reply if no model is configured


def test_understood_but_invalid_answers_are_not_sent_to_the_model() -> None:
    sim = _at_land_area()
    assert _send(sim, Inbound(text="900")).unread is None  # out of range
    assert _send(sim, Inbound(text="2 kg")).unread is None  # wrong unit


def test_model_reading_is_confirmed_before_it_is_saved() -> None:
    sim = _at_land_area()
    step = _send(sim, Inbound(text="kira2 setengah hektar lebih dikit", ai_text="0,5"))
    assert step.unread is None
    assert step.replies[0].text == copy.confirm_value("0,5 ha")
    assert "land_area" not in step.state.answers
    sim.state = step.state
    sim.tap("yes")
    assert sim.state.answers["land_area"] == "0.5"
    assert sim.state.step == "condition"


def test_model_reading_out_of_range_says_why() -> None:
    step = _send(_at_land_area(), Inbound(text="sembilan ratusan hektar", ai_text="900"))
    assert step.replies[0].text == copy.out_of_range(0, 500, "ha")
    assert step.unread is None and step.state.pending is None


def test_unusable_model_reading_falls_back_to_asking_again() -> None:
    step = _send(_at_land_area(), Inbound(text="lumayan", ai_text="entahlah"))
    assert step.replies[0].text == copy.NOT_A_NUMBER
    assert step.unread is None  # no second round trip


def test_choice_reading_asks_did_you_mean() -> None:
    sim = _at_land_area()
    sim.say("1,5")
    assert sim.state.step == "condition"
    assert _send(sim, Inbound(text="daunnya pada bolong dimakan ulat")).unread == "condition"
    step = _send(sim, Inbound(text="daunnya pada bolong dimakan ulat", ai_text="Terserang"))
    assert step.replies[0].text == copy.did_you_mean("Terserang")
    assert step.state.pending == {"field": "condition", "value": "infected", "display": "Terserang"}


def test_text_questions_never_need_the_model() -> None:
    sim = _at_land_area()
    sim.state.step = "farmer_name"
    sim.state.answers.pop("farmer_name", None)
    assert _send(sim, Inbound(text="??")).unread is None


# --- Spoken answers (roadmap 12.7) --------------------------------------------------------------


def _voice(transcript: str | None, **extra: object) -> Inbound:
    media = Media("voice", "workspaces/w/messages/2026/11/v.ogg")
    spoken = transcript is not None
    return Inbound(text=transcript, spoken=spoken, media=media, **extra)  # type: ignore[arg-type]


def test_untranscribed_voice_note_asks_to_type() -> None:
    step = _send(_at_land_area(), _voice(None))
    assert step.replies[0].text == copy.VOICE_LATER
    assert step.unread is None


def test_spoken_number_is_confirmed_before_saving() -> None:
    sim = _at_land_area()
    step = _send(sim, _voice("1,5 hektar."))
    assert step.replies[0].text == copy.confirm_value("1,5 ha")
    assert "land_area" not in step.state.answers
    sim.state = step.state
    sim.tap("yes")
    assert sim.state.answers["land_area"] == "1.5"


def test_spoken_name_is_confirmed_too() -> None:
    sim = _at_land_area()
    sim.state.step = "farmer_name"
    sim.state.answers.pop("farmer_name", None)
    step = _send(sim, _voice("Pak Slamet Riyadi"))
    assert step.replies[0].text == copy.confirm_value("Pak Slamet Riyadi")


def test_misheard_number_goes_to_the_language_model() -> None:
    sim = _at_land_area()
    assert _send(sim, _voice("satu hektar seperempat")).unread == "land_area"
    step = _send(sim, _voice("satu hektar seperempat", ai_text="1,25"))
    assert step.replies[0].text == copy.confirm_value("1,25 ha")


def test_spoken_skip_command_works() -> None:
    sim = _at_land_area()
    sim.say("1,5")
    sim.tap("opt:healthy")
    assert sim.state.step == "photos"
    step = _send(sim, _voice("Lewati."))
    assert "photos" in step.state.answers and step.state.answers["photos"] is None
