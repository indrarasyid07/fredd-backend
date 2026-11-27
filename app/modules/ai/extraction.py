"""Reading several field values out of one spoken sentence (roadmap 12.1, Voice Lab).

    "Sampel S-2041, pH 6,8, suhu 25 derajat, volume 50 mililiter"
      → sample = "S-2041", ph = 6.8, temp = 25 (°C), volume = 50 (mL)

Deterministic, no network: each field is found by its cues (its label, its key, and the spoken
examples an admin adds in roadmap 12.2), and the words up to the next cue are read with the
same parsers as the chat (numbers, choices, dates). Every value carries a confidence; anything
below `CONFIDENT` is asked again (roadmap 12.3), never silently kept. A language model may later
read what this cannot (roadmap 12.7), still under the same rule.
"""

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.conversations.engine.parsers import (
    DEFAULT_UNITS,
    Choice,
    parse_choice,
    parse_date,
    parse_multi_choice,
    parse_number,
)
from app.modules.forms.constants import SPOKEN_TYPES
from app.modules.forms.schemas import DraftFormDefinition, FieldDefinition, FormDefinition

# At or above: kept as heard. Below: the analyst is asked to confirm or repeat.
CONFIDENT = 0.7
# More words than this in a short text answer, or a comma, and it is doubtful.
SHORT_TEXT_WORDS = 6

# Units said in labs, on top of the chat's (ha, kg, °C, rupiah...). Alias → unit code.
LAB_UNITS: dict[str, str] = {
    "ml": "ml",
    "mililiter": "ml",
    "milliliter": "ml",
    "liter": "l",
    "mg": "mg",
    "miligram": "mg",
    "milligram": "mg",
    "gram": "g",
    "mikroliter": "ul",
    "µl": "ul",
    "ul": "ul",
    "ppm": "ppm",
    "mg/l": "mg_l",
    "persen": "percent",
    "%": "percent",
    "rpm": "rpm",
    "menit": "minute",
    "detik": "second",
    "jam": "hour",
    "kelvin": "kelvin",
    "mol": "mol",
    "molar": "molar",
}
UNITS = {**DEFAULT_UNITS, **LAB_UNITS}

# Words between a cue and its value that carry nothing ("pH-nya adalah 6,8").
_FILLER = re.compile(r"^(?:(?:nya|adalah|yaitu|ialah|sebesar|=|:)(?:\s+|$|(?=\d)))+", re.IGNORECASE)
_TRIM = " ,.;:-–—\t"
# A minus sign is a dash right before a digit ("suhu -20 derajat"); it is kept by `_trim`.
_NEGATIVE = re.compile(r"^[-−]\d")


def _trim(words: str) -> str:
    """The words without separators around them, keeping a leading minus sign."""
    trimmed = words.strip(_TRIM)
    return "-" + trimmed if _NEGATIVE.match(words.strip()) else trimmed


@dataclass(frozen=True)
class ExtractedValue:
    field_key: str
    # Stored like a chat answer: numbers as decimal strings, choices as their value (a list for
    # multiple choice), dates as ISO strings, text as said.
    value: Any
    display: str
    confidence: float
    # The words this value was read from, for highlighting in the transcript.
    heard: str
    # Why the confidence is low, for the question asked again; None when confident.
    doubt: str | None = None


@dataclass
class Extraction:
    values: list[ExtractedValue] = field(default_factory=list)
    # Required fields that were not said at all.
    missing: list[str] = field(default_factory=list)

    def value(self, key: str) -> ExtractedValue | None:
        return next((v for v in self.values if v.field_key == key), None)

    @property
    def unsure(self) -> list[ExtractedValue]:
        return [v for v in self.values if v.confidence < CONFIDENT]


def unit_code(unit: str | None) -> str | None:
    """A field's unit ("°C", "mL", "ha") as the code spoken units map to."""
    if not unit:
        return None
    return UNITS.get(unit.strip().lower(), unit.strip().lower())


def extract(
    text: str,
    definition: FormDefinition | DraftFormDefinition,
    *,
    cues: Mapping[str, Sequence[str]] | None = None,
    today: dt.date | None = None,
) -> Extraction:
    """Every field value said in `text`. Each field's `voice_cues` and `unit_aliases` (roadmap
    12.2) are used; `cues` adds more spoken names per field key."""
    said = re.sub(r"\s+", " ", text).strip()
    fields = [f for f in definition.fields if f.type in SPOKEN_TYPES]
    found = _locate(said, fields, cues or {})
    out = Extraction()
    for i, (_start, end, f) in enumerate(found):
        stop = found[i + 1][0] if i + 1 < len(found) else len(said)
        words = _trim(_FILLER.sub("", _trim(said[end:stop])))
        value = _read(f, words, today or dt.date.today())
        if value is not None:
            out.values.append(value)
    heard = {v.field_key for v in out.values}
    out.missing = [f.key for f in definition.fields if f.required and f.key not in heard]
    return out


def _cues(f: FieldDefinition, extra: Sequence[str]) -> list[str]:
    names = [f.label, f.key.replace("_", " "), *f.voice_cues, *extra]
    return sorted({n.strip().lower() for n in names if n.strip()}, key=len, reverse=True)


def _locate(
    said: str, fields: list[FieldDefinition], cues: Mapping[str, Sequence[str]]
) -> list[tuple[int, int, FieldDefinition]]:
    """(start, end, field) of the first cue of each field, in the order spoken. Longer cues win
    over shorter ones they overlap ("suhu ruang" before "suhu")."""
    candidates: list[tuple[int, int, FieldDefinition]] = []
    for f in fields:
        for cue in _cues(f, cues.get(f.key, ())):
            pattern = re.compile(rf"(?<![\w]){re.escape(cue)}(?![\w])", re.IGNORECASE)
            candidates.extend((m.start(), m.end(), f) for m in pattern.finditer(said))
    candidates.sort(key=lambda c: (c[0], -(c[1] - c[0])))
    taken: list[tuple[int, int, FieldDefinition]] = []
    seen: set[str] = set()
    for start, end, f in candidates:
        if f.key in seen or any(start < e and end > s for s, e, _ in taken):
            continue
        taken.append((start, end, f))
        seen.add(f.key)
    return sorted(taken, key=lambda c: c[0])


def read_value(
    f: FieldDefinition, words: str, today: dt.date | None = None
) -> ExtractedValue | None:
    """One field's value from words already known to be its answer (a supervisor's correction,
    roadmap 12.5), read with the same rules as a spoken sentence."""
    return _read(f, _trim(words), today or dt.date.today())


def _read(f: FieldDefinition, words: str, today: dt.date) -> ExtractedValue | None:
    if not words:
        return None
    if f.type == "number":
        return _number(f, words)
    if f.type in ("single_choice", "multi_choice"):
        return _choice(f, words)
    if f.type == "datetime":
        day = parse_date(words, today=today)
        if day is None:
            return ExtractedValue(f.key, None, words, 0.0, words, "Tanggal tidak terbaca")
        return ExtractedValue(f.key, day.isoformat(), day.strftime("%d/%m/%Y"), 0.9, words)
    if f.type == "short_text" and ("," in words or len(words.split()) > SHORT_TEXT_WORDS):
        # A short answer (a sample number, a name) that ran on: it likely swallowed the next
        # values because their names were not recognised ("S-9 asamnya netral tujuh, ...").
        return ExtractedValue(f.key, words, words, 0.5, words, "Sepertinya ikut terbawa kata lain")
    # Free text is kept as said; it is never wrong, only possibly misheard.
    return ExtractedValue(f.key, words, words, 0.75, words)


def _number(f: FieldDefinition, words: str) -> ExtractedValue:
    expected = unit_code(f.unit)
    # Words the admin listed for this field's unit ("derajat") mean exactly that unit.
    own = {a.lower(): expected for a in f.unit_aliases if expected}
    parsed = parse_number(words, {**LAB_UNITS, **own})
    if parsed is None:
        return ExtractedValue(f.key, None, words, 0.0, words, "Angka tidak terbaca")
    text = f"{parsed.value.normalize():f}"
    display = text.replace(".", ",") + (f" {f.unit}" if f.unit else "")
    if parsed.unit and expected and parsed.unit != expected:
        doubt = f"Satuan yang terdengar bukan {f.unit}"
        return ExtractedValue(f.key, text, display, 0.4, words, doubt)
    if f.min is not None and parsed.value < f.min or f.max is not None and parsed.value > f.max:
        return ExtractedValue(f.key, text, display, 0.5, words, "Di luar batas isian")
    # A unit said and matching is the surest; none said is still likely right.
    confidence = 0.95 if parsed.unit and expected else 0.85
    return ExtractedValue(f.key, text, display, confidence, words)


def _choice(f: FieldDefinition, words: str) -> ExtractedValue:
    options = [Choice(o.value, o.label) for o in f.options]
    if f.type == "multi_choice":
        result = parse_multi_choice(words, options)
        if not result.matches:
            return ExtractedValue(f.key, None, words, 0.0, words, "Pilihan tidak dikenali")
        values = [m.value for m in result.matches]
        display = ", ".join(m.label for m in result.matches)
        unsure = result.unknown or any(m.needs_confirmation for m in result.matches)
        doubt = "Sebagian pilihan tidak dikenali" if unsure else None
        return ExtractedValue(f.key, values, display, 0.5 if unsure else 0.9, words, doubt)
    match = parse_choice(words, options)
    if match is None:
        return ExtractedValue(f.key, None, words, 0.0, words, "Pilihan tidak dikenali")
    if match.needs_confirmation:
        return ExtractedValue(f.key, match.value, match.label, 0.5, words, "Mirip pilihan lain")
    return ExtractedValue(f.key, match.value, match.label, 0.9, words)
