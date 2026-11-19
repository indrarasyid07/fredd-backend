"""`FormDefinition`: the shape of `form_versions.definition`, shared by every domain.

The conversation engine asks the fields in order and applies the rules; reports copy the
`condition` and `area` answers into filter columns. Keys and option values are English and
stable (data, analytics); `label`, `question` and option labels are Indonesian (people see them).

Every problem is reported at once with a dotted path (`fields.2.options`) and an
`app_code` in the error context, so the API returns one `errors[]` item per problem.
"""

from typing import Annotated, Any, LiteralString, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from app.modules.forms.constants import (
    ANSWER_MODES_BY_TYPE,
    BOUNDED_TYPES,
    CHOICE_TYPES,
    CONDITION_VALUES,
    MAX_FIELDS,
    MAX_OPTIONS,
    MAX_RULES,
    AnswerMode,
    FieldRole,
    FieldType,
)

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=50)]
Color = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChoiceOption(_Strict):
    value: Key
    label: str = Field(min_length=1, max_length=100)
    # Shared with the dashboard map for the answers of a condition field.
    color: Color | None = None


class FieldDefinition(_Strict):
    key: Key
    type: FieldType
    # Column title in the dashboard.
    label: str = Field(min_length=1, max_length=100)
    # What Fluctuz asks in chat.
    question: str = Field(min_length=1, max_length=500)
    required: bool = True
    # number: the value; multi_choice: how many options; photo/video/document: how many files.
    min: float | None = None
    max: float | None = None
    # number: answers above this go to the review queue.
    review_above: float | None = None
    # number only, e.g. "ha", "kg", "Rp".
    unit: str | None = Field(default=None, max_length=20)
    # single_choice and multi_choice only.
    options: list[ChoiceOption] = Field(default_factory=list, max_length=MAX_OPTIONS)
    # Empty = every mode of the type is allowed.
    answer_modes: list[AnswerMode] = Field(default_factory=list)
    role: FieldRole | None = None
    # location only: a shared point less accurate than this is asked again.
    max_accuracy_m: int | None = Field(default=None, gt=0, le=10_000)


class RuleCondition(_Strict):
    field: Key
    # For multi_choice, "equals" means "includes this option".
    equals: str | float | bool


class RuleAction(_Strict):
    # Make this field required.
    require: Key | None = None
    # Send the report to the review queue.
    needs_review: bool = False


class Rule(_Strict):
    """IF `if.field` equals `if.equals` THEN `then` (JIKA ... MAKA ... in the UI)."""

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, serialize_by_alias=True, validate_by_alias=True
    )

    if_: RuleCondition = Field(alias="if")
    then: RuleAction


class FormDefinition(_Strict):
    fields: list[FieldDefinition] = Field(min_length=1, max_length=MAX_FIELDS)
    rules: list[Rule] = Field(default_factory=list, max_length=MAX_RULES)

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = _Problems()
        _check_fields(self.fields, problems)
        _check_rules(self, problems)
        problems.raise_if_any(self)
        return self

    def field(self, key: str) -> FieldDefinition | None:
        return next((f for f in self.fields if f.key == key), None)

    def field_with_role(self, role: str) -> FieldDefinition | None:
        return next((f for f in self.fields if f.role == role), None)

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


# Message per problem code; codes never change once the frontend uses them.
MESSAGES: dict[str, LiteralString] = {
    "duplicate_field_key": "Kunci isian sudah dipakai isian lain.",
    "options_too_few": "Isian pilihan butuh minimal 2 pilihan.",
    "options_not_allowed": "Hanya isian pilihan yang punya daftar pilihan.",
    "duplicate_option": "Pilihan ini sudah ada.",
    "bounds_not_allowed": "Batas minimal/maksimal tidak berlaku untuk tipe ini.",
    "invalid_range": "Batas maksimal harus lebih besar dari batas minimal.",
    "negative_count": "Jumlah minimal tidak boleh negatif.",
    "review_above_not_allowed": "Batas tinjauan hanya untuk isian angka.",
    "unit_not_allowed": "Satuan hanya untuk isian angka.",
    "accuracy_not_allowed": "Akurasi hanya untuk isian lokasi.",
    "invalid_answer_mode": "Cara menjawab ini tidak berlaku untuk tipe isian ini.",
    "duplicate_role": "Peran isian ini sudah dipakai isian lain.",
    "condition_not_single_choice": "Isian kondisi harus berupa pilihan tunggal.",
    "area_not_number": "Isian luas harus berupa angka.",
    "invalid_condition_value": "Nilai kondisi harus healthy, attention, atau infected.",
    "invalid_area_unit": "Isian luas memakai satuan ha.",
    "unknown_field": "Aturan merujuk isian yang tidak ada.",
    "unknown_option": "Nilai ini tidak ada di pilihan isian.",
    "empty_rule_action": "Aturan butuh tindakan MAKA.",
    "self_reference": "Aturan tidak boleh mewajibkan isian pemicunya sendiri.",
}


class _Problems:
    def __init__(self) -> None:
        self.items: list[InitErrorDetails] = []

    def add(self, loc: tuple[str | int, ...], code: LiteralString, value: object) -> None:
        error = PydanticCustomError(code, MESSAGES[code], {"app_code": code})
        self.items.append(InitErrorDetails(type=error, loc=loc, input=value))

    def raise_if_any(self, model: BaseModel) -> None:
        if self.items:
            raise ValidationError.from_exception_data(type(model).__name__, self.items)


def _check_fields(fields: list[FieldDefinition], p: _Problems) -> None:
    seen: set[str] = set()
    roles: set[str] = set()
    for i, f in enumerate(fields):
        at = ("fields", i)
        if f.key in seen:
            p.add((*at, "key"), "duplicate_field_key", f.key)
        seen.add(f.key)

        is_choice = f.type in CHOICE_TYPES
        if is_choice and len(f.options) < 2:
            p.add((*at, "options"), "options_too_few", None)
        if not is_choice and f.options:
            p.add((*at, "options"), "options_not_allowed", None)
        values = [o.value for o in f.options]
        for j, value in enumerate(values):
            if value in values[:j]:
                p.add((*at, "options", j, "value"), "duplicate_option", value)

        if f.type not in BOUNDED_TYPES and (f.min is not None or f.max is not None):
            p.add((*at, "min"), "bounds_not_allowed", f.min)
        if f.min is not None and f.max is not None and f.min > f.max:
            p.add((*at, "max"), "invalid_range", f.max)
        if f.type != "number" and f.min is not None and f.min < 0:
            p.add((*at, "min"), "negative_count", f.min)
        if f.type != "number" and f.review_above is not None:
            p.add((*at, "review_above"), "review_above_not_allowed", f.review_above)
        if f.type != "number" and f.unit:
            p.add((*at, "unit"), "unit_not_allowed", f.unit)
        if f.type != "location" and f.max_accuracy_m is not None:
            p.add((*at, "max_accuracy_m"), "accuracy_not_allowed", f.max_accuracy_m)

        allowed_modes = ANSWER_MODES_BY_TYPE[f.type]
        for j, mode in enumerate(f.answer_modes):
            if mode not in allowed_modes or mode in f.answer_modes[:j]:
                p.add((*at, "answer_modes", j), "invalid_answer_mode", mode)

        if f.role:
            if f.role in roles:
                p.add((*at, "role"), "duplicate_role", f.role)
            roles.add(f.role)
        if f.role == "condition":
            if f.type != "single_choice":
                p.add((*at, "type"), "condition_not_single_choice", f.type)
            for j, value in enumerate(values):
                if value not in CONDITION_VALUES:
                    p.add((*at, "options", j, "value"), "invalid_condition_value", value)
        if f.role == "area":
            if f.type != "number":
                p.add((*at, "type"), "area_not_number", f.type)
            if f.unit not in (None, "ha"):
                p.add((*at, "unit"), "invalid_area_unit", f.unit)


def _check_rules(d: FormDefinition, p: _Problems) -> None:
    for i, rule in enumerate(d.rules):
        at = ("rules", i)
        source = d.field(rule.if_.field)
        if source is None:
            p.add((*at, "if", "field"), "unknown_field", rule.if_.field)
        elif source.type in CHOICE_TYPES:
            if rule.if_.equals not in [o.value for o in source.options]:
                p.add((*at, "if", "equals"), "unknown_option", rule.if_.equals)
        action = rule.then
        if action.require is None and not action.needs_review:
            p.add((*at, "then"), "empty_rule_action", None)
        if action.require is not None:
            if d.field(action.require) is None:
                p.add((*at, "then", "require"), "unknown_field", action.require)
            elif action.require == rule.if_.field:
                p.add((*at, "then", "require"), "self_reference", action.require)
