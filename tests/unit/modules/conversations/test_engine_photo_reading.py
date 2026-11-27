"""Baca struk dan foto: a photo sent to a field with `read_values` is read by a language model
for the answers not given yet; every value is checked with the same rules and confirmed one by
one, and nothing already answered is replaced."""

import json
from dataclasses import replace
from pathlib import Path

from app.modules.conversations.engine import copy
from app.modules.conversations.engine.machine import handle
from app.modules.conversations.engine.simulator import SimTopic, Simulator
from app.modules.conversations.engine.types import Inbound, Media, Step
from app.modules.forms.schemas import FormDefinition

_FIXTURE = json.loads(
    (Path(__file__).parents[4] / "fixtures" / "demo" / "structures.json").read_text("utf-8")
)
SALES = FormDefinition.model_validate(
    next(s for s in _FIXTURE["structures"] if s["name"] == "Catatan Penjualan Hasil Panen")[
        "definition"
    ]
)
READ = {
    "sale_date": "2026-11-27",
    "buyer": "UD Tani Makmur",
    "commodity": "Padi",
    "weight": "125,5",
    "total": "1250000",
}
# Not the notes: long text is the worker's own words.
ALL_KEYS = ("sale_date", "buyer", "commodity", "weight", "price_per_kg", "total")


def _sales(definition: FormDefinition = SALES) -> Simulator:
    sim = Simulator(topics=[SimTopic("s", "Dinas · Penjualan", definition, "K7M29QXA")])
    sim.say("GABUNG K7M2-9QXA")
    sim.say("mulai")
    assert sim.state.step == "receipt"
    return sim


def _photo(sim: Simulator, ai_values: dict[str, str] | None = None) -> Step:
    message = Inbound(media=Media("photo", "workspaces/w/messages/nota.jpg"), ai_values=ai_values)
    return handle(sim.state, message, sim._context())


def test_receipt_photo_is_marked_for_reading() -> None:
    step = _photo(_sales())
    assert step.read_photo == "workspaces/w/messages/nota.jpg"
    assert step.read_keys == ALL_KEYS
    assert step.state.answers["receipt"] == ["workspaces/w/messages/nota.jpg"]  # kept anyway


def test_read_values_are_confirmed_one_by_one() -> None:
    sim = _sales()
    step = _photo(sim, READ)
    assert step.read_photo is None  # no second round trip
    note, received = step.replies
    assert note.text == copy.photo_read(
        [("Tanggal jual", "27/11/2026"), ("Pembeli", "UD Tani Makmur"), ("Komoditas", "Padi"),
         ("Berat", "125,5 kg"), ("Total", "1250000 Rp")]
    )  # fmt: skip
    assert received.buttons[0].value == "done"  # up to 2 photos: another may follow
    assert "sale_date" not in step.state.answers  # nothing kept before "Ya"

    sim.state = step.state
    assert sim.tap("done")[0].text == copy.confirm_value("27/11/2026")
    assert sim.tap("yes")[0].text == copy.confirm_value("UD Tani Makmur")
    assert sim.tap("yes")[0].text == copy.did_you_mean("Padi")
    assert sim.tap("yes")[0].text == copy.confirm_value("125,5 kg")
    (price,) = sim.tap("yes")
    assert "harga per kilogram" in price.text  # not on the receipt: asked as usual
    sim.tap("skip")
    assert "Ada catatan" in sim.tap("yes")[0].text  # total confirmed, then notes
    assert sim.state.answers["total"] == "1250000"
    assert sim.state.answers["weight"] == "125.5"
    assert sim.state.answers["commodity"] == "rice"


def test_rejected_value_is_asked_normally() -> None:
    sim = _sales()
    sim.state = _photo(sim, READ).state
    sim.tap("done")
    (question,) = sim.tap("no")
    assert "Tanggal berapa" in question.text


def test_unreadable_photo_says_so_and_asks_as_usual() -> None:
    sim = _sales()
    step = _photo(sim, {})
    assert step.replies[0].text == copy.PHOTO_VALUES_UNREAD
    sim.state = step.state
    assert "Tanggal berapa" in sim.tap("done")[0].text


def test_values_breaking_the_rules_are_dropped() -> None:
    step = _photo(_sales(), {"weight": "banyak", "total": "-5", "commodity": "Durian"})
    assert step.replies[0].text == copy.PHOTO_VALUES_UNREAD  # none survived the checks


def test_answers_already_given_are_never_read_again() -> None:
    sim = _sales()
    sim.state.answers["buyer"] = "Pak Dadang"
    step = _photo(sim)
    assert "buyer" not in step.read_keys
    step = _photo(sim, {**READ, "buyer": "Orang lain"})
    assert "buyer" not in step.state.ai_suggested


def test_a_field_without_read_values_is_not_read() -> None:
    plain = SALES.model_copy(
        update={"fields": [replace_field(SALES.fields[0], read_values=False), *SALES.fields[1:]]}
    )
    assert _photo(_sales(plain)).read_photo is None


def test_a_document_file_is_not_read() -> None:
    sim = _sales()
    step = handle(sim.state, Inbound(media=Media("document", "w/nota.pdf")), sim._context())
    assert step.read_photo is None


def test_receipt_sent_before_mulai_is_read_too() -> None:
    sim = Simulator(topics=[SimTopic("s", "Dinas · Penjualan", SALES, "K7M29QXA")])
    sim.say("GABUNG K7M2-9QXA")
    sim.tap("join:keep") if sim.state.status == "joining" else None
    sim.state = replace(sim.state, status="idle", step=None)
    photo = Inbound(media=Media("photo", "workspaces/w/messages/nota.jpg"))
    step = handle(sim.state, photo, sim._context())
    assert step.read_photo == "workspaces/w/messages/nota.jpg" and step.read_keys == ALL_KEYS
    step = handle(sim.state, replace(photo, ai_values=READ), sim._context())
    note, greeting = step.replies[-2:]
    assert note.text.startswith("Dari foto, sepertinya: Tanggal jual *27/11/2026*")
    assert copy.confirm_value("27/11/2026") in greeting.text  # the first question is a check


def replace_field(field, **changes):  # noqa: ANN001, ANN201
    return field.model_copy(update=changes)
