from typing import Any

import pytest
from pydantic import ValidationError

from app.api.errors import _validation_item
from app.modules.forms.schemas import MESSAGES, FormDefinition
from tests.form_definitions import crop_survey


def problems(data: dict[str, Any]) -> list[tuple[str, str]]:
    """(dotted path, code) of every problem, as the API reports them in errors[]."""
    with pytest.raises(ValidationError) as caught:
        FormDefinition.model_validate(data)
    items = [_validation_item({**e, "loc": ("body", *e["loc"])}) for e in caught.value.errors()]
    return [(i.field or "", i.code) for i in items]


def test_crop_survey_is_valid_and_round_trips() -> None:
    definition = FormDefinition.model_validate(crop_survey())

    assert definition.field_with_role("condition").key == "condition"  # type: ignore[union-attr]
    assert definition.field_with_role("area").key == "land_area"  # type: ignore[union-attr]
    stored = definition.to_json()
    assert stored["rules"][0]["if"] == {"field": "condition", "equals": "infected"}
    assert FormDefinition.model_validate(stored) == definition


def test_every_problem_is_reported_with_its_path() -> None:
    data = crop_survey()
    data["fields"][1]["key"] = "location"  # duplicate
    data["fields"][1]["unit"] = "kg"  # text has no unit
    data["fields"][3]["options"][1]["value"] = "needs_attention"  # not a condition value
    data["rules"][0]["then"]["require"] = "photo"  # unknown field

    assert sorted(problems(data)) == [
        ("fields.1.key", "duplicate_field_key"),
        ("fields.1.unit", "unit_not_allowed"),
        ("fields.3.options.1.value", "invalid_condition_value"),
        ("rules.0.then.require", "unknown_field"),
    ]


def test_message_is_the_indonesian_catalog_text() -> None:
    data = crop_survey()
    data["fields"][3]["options"] = data["fields"][3]["options"][:1]
    with pytest.raises(ValidationError) as caught:
        FormDefinition.model_validate(data)
    item = _validation_item({**caught.value.errors()[0], "loc": ("body", "fields", 3, "options")})
    assert (item.code, item.message) == ("options_too_few", MESSAGES["options_too_few"])


@pytest.mark.parametrize(
    ("index", "change", "expected"),
    [
        (
            0,
            {"options": [{"value": "a", "label": "A"}]},
            ("fields.0.options", "options_not_allowed"),
        ),
        (1, {"min": 1}, ("fields.1.min", "bounds_not_allowed")),
        (2, {"min": 10, "max": 5}, ("fields.2.max", "invalid_range")),
        (4, {"min": -1}, ("fields.4.min", "negative_count")),
        (4, {"review_above": 2}, ("fields.4.review_above", "review_above_not_allowed")),
        (1, {"max_accuracy_m": 10}, ("fields.1.max_accuracy_m", "accuracy_not_allowed")),
        (0, {"answer_modes": ["map", "draw"]}, ("fields.0.answer_modes.1", "invalid_answer_mode")),
        (0, {"answer_modes": ["map", "map"]}, ("fields.0.answer_modes.1", "invalid_answer_mode")),
        (1, {"role": "area"}, ("fields.1.type", "area_not_number")),
        (2, {"unit": "m2"}, ("fields.2.unit", "invalid_area_unit")),
        (3, {"type": "multi_choice"}, ("fields.3.type", "condition_not_single_choice")),
    ],
)
def test_field_constraints(index: int, change: dict[str, Any], expected: tuple[str, str]) -> None:
    data = crop_survey()
    data["fields"][index].update(change)
    assert expected in problems(data)


def test_one_field_per_role() -> None:
    data = crop_survey()
    data["fields"].append({**data["fields"][2], "key": "land_area_2"})
    assert problems(data) == [("fields.5.role", "duplicate_role")]


def test_duplicate_option_values() -> None:
    data = crop_survey()
    data["fields"][3]["options"][1]["value"] = "healthy"
    assert problems(data) == [("fields.3.options.1.value", "duplicate_option")]


IF_INFECTED = {"field": "condition", "equals": "infected"}
REQUIRE_PHOTOS = {"require": "photos"}


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (
            {"if": {"field": "x", "equals": "a"}, "then": REQUIRE_PHOTOS},
            ("rules.0.if.field", "unknown_field"),
        ),
        (
            {"if": {"field": "condition", "equals": "dead"}, "then": REQUIRE_PHOTOS},
            ("rules.0.if.equals", "unknown_option"),
        ),
        ({"if": IF_INFECTED, "then": {}}, ("rules.0.then", "empty_rule_action")),
        (
            {"if": {"field": "photos", "equals": 1}, "then": REQUIRE_PHOTOS},
            ("rules.0.then.require", "self_reference"),
        ),
    ],
)
def test_rule_references(rule: dict[str, Any], expected: tuple[str, str]) -> None:
    data = {**crop_survey(), "rules": [rule]}
    assert problems(data) == [expected]


def test_shape_errors_come_from_pydantic() -> None:
    assert problems({"fields": []}) == [("fields", "validation_error")]
    data = crop_survey()
    data["fields"][0]["key"] = "Lokasi Lahan"
    data["fields"][0]["colour"] = "red"
    assert sorted(problems(data)) == [
        ("fields.0.colour", "validation_error"),
        ("fields.0.key", "validation_error"),
    ]
