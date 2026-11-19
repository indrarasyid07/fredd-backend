"""Read Indonesian chat answers: numbers, dates, choices, yes/no (conversation-engine.md).

Pure functions, no I/O: the engine passes the field's options, unit aliases from reference data
and "today" in the workspace's time zone. Each parser returns None when it cannot read the answer
with confidence; the engine then asks again with an example instead of guessing. Fuzzy choice
matches are flagged `needs_confirmation` ("Maksud Anda Padi?").
"""

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

# --- Shared -------------------------------------------------------------------------------------

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, single spaces, no surrounding punctuation."""
    text = _SPACES.sub(" ", text.strip().lower())
    return text.strip(" .!?;:\"'")


# --- Numbers ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedNumber:
    value: Decimal
    # Unit code the answer named ("ha", "kg", "rupiah"...), None when it named none.
    unit: str | None = None


# Alias → unit code, matching the platform units in fixtures/reference/commodities.json.
DEFAULT_UNITS: dict[str, str] = {
    "ha": "ha",
    "hektar": "ha",
    "hektare": "ha",
    "hektaran": "ha",
    "kg": "kg",
    "kilo": "kg",
    "kilogram": "kg",
    "kw": "quintal",
    "ku": "quintal",
    "kwintal": "quintal",
    "kuintal": "quintal",
    "ton": "ton",
    "m2": "m2",
    "m²": "m2",
    "meter persegi": "m2",
    "rupiah": "rupiah",
    "orang": "person",
    "org": "person",
    "jiwa": "person",
    "ekor": "head",
    "batang": "plant",
    "pohon": "plant",
    "rumpun": "plant",
    "karung": "sack",
    "sak": "sack",
    "zak": "sack",
    "°c": "celsius",
    "derajat": "celsius",
    "celsius": "celsius",
    "celcius": "celsius",
}

# Words people put around a number without changing it.
_HEDGES = re.compile(
    r"^(sekitar|kira-kira|kira kira|kurang lebih|kurleb|lebih kurang|±|\+-|cuma|hanya|ada|"
    r"sebanyak|total|jumlahnya|luasnya)\s+"
)
_RUPIAH_PREFIX = re.compile(r"^rp\.?\s*")

_THOUSANDS = re.compile(r"^-?\d{1,3}(?:\.\d{3})+(?:,\d+)?$")  # 1.250.000 / 1.500,75
_COMMA_DECIMAL = re.compile(r"^-?\d+(?:,\d+)?$")  # 15 / 1,5
_DOT_DECIMAL = re.compile(r"^-?\d+\.\d+$")  # 1.5 (dot + 3 digits is thousands, above)
_FRACTION = re.compile(r"^(\d+)/(\d+)$")
_MIXED = re.compile(r"^(\d+) (\d+)/(\d+)$")

_DIGITS = {
    "nol": 0,
    "kosong": 0,
    "satu": 1,
    "se": 1,
    "dua": 2,
    "tiga": 3,
    "empat": 4,
    "lima": 5,
    "enam": 6,
    "tujuh": 7,
    "delapan": 8,
    "sembilan": 9,
}
_FRACTIONS = {"setengah": Decimal("0.5"), "seperempat": Decimal("0.25")}


def parse_number(text: str, units: Mapping[str, str] | None = None) -> ParsedNumber | None:
    """ "1,5", "1.500", "Rp 1.250.000", "2 ha", "satu setengah", "3/4" → a number and its unit."""
    t = normalize(text)
    t = re.sub(r",-$", "", t).rstrip("-").strip()
    t = _HEDGES.sub("", t)
    unit = None
    if _RUPIAH_PREFIX.match(t):
        unit = "rupiah"
        t = _RUPIAH_PREFIX.sub("", t)
    aliases = {**DEFAULT_UNITS, **{k.lower(): v for k, v in (units or {}).items()}}
    for alias in sorted(aliases, key=len, reverse=True):
        if t.endswith(alias):
            rest = t[: -len(alias)]
            # The alias must stand alone or follow a digit ("2ha"), not end a longer word.
            if rest and not (rest.endswith(" ") or rest[-1].isdigit()):
                continue
            unit = aliases[alias]
            t = rest.strip()
            break
    if not t:
        return None
    value = _numeric(t)
    if value is None:
        value = _words(t)
    return ParsedNumber(value, unit) if value is not None else None


def _numeric(t: str) -> Decimal | None:
    try:
        if m := _MIXED.match(t):
            whole, num, den = (int(g) for g in m.groups())
            return Decimal(whole) + Decimal(num) / Decimal(den) if den else None
        if m := _FRACTION.match(t):
            num, den = (int(g) for g in m.groups())
            return Decimal(num) / Decimal(den) if den else None
        if _THOUSANDS.match(t):
            return Decimal(t.replace(".", "").replace(",", "."))
        if _COMMA_DECIMAL.match(t):
            return Decimal(t.replace(",", "."))
        if _DOT_DECIMAL.match(t):
            return Decimal(t)
    except InvalidOperation:
        return None
    return None


def _words(t: str) -> Decimal | None:
    """Indonesian number words: "dua ratus lima puluh", "satu setengah", "dua koma lima"."""
    if " koma " in f" {t} ":
        left, _, right = t.partition("koma")
        whole = _integer_words(left.split()) if left.strip() else 0
        digits = [_DIGITS.get(w) for w in right.split()]
        if whole is None or not digits or any(d is None for d in digits):
            return None
        return Decimal(f"{whole}.{''.join(str(d) for d in digits)}")
    tokens = t.split()
    if tokens and tokens[-1] in _FRACTIONS:
        whole = _integer_words(tokens[:-1]) if tokens[:-1] else 0
        return None if whole is None else Decimal(whole) + _FRACTIONS[tokens[-1]]
    whole = _integer_words(tokens)
    return Decimal(whole) if whole is not None else None


def _integer_words(tokens: Sequence[str]) -> int | None:
    # Split "seratus", "seribu", "sebelas"... into "se" + multiplier.
    expanded: list[str] = []
    for token in tokens:
        if token.startswith("se") and token[2:] in ("puluh", "belas", "ratus", "ribu", "juta"):
            expanded += ["se", token[2:]]
        else:
            expanded.append(token)
    if not expanded:
        return None
    total, group, last = 0, 0, 0
    previous_was_digit = False
    for word in expanded:
        if word in _DIGITS:
            if previous_was_digit:
                return None  # "dua tiga": two numbers, not one
            last = _DIGITS[word]
            group += last
            previous_was_digit = True
            continue
        if not previous_was_digit and word in ("puluh", "belas", "ratus"):
            return None
        if word == "puluh":
            group += last * 9  # the last digit becomes tens
        elif word == "belas":
            group += 10
        elif word == "ratus":
            group += last * 99
        elif word == "ribu":
            total += (group or 1) * 1_000
            group = 0
        elif word == "juta":
            total += (group or 1) * 1_000_000
            group = 0
        else:
            return None
        last = 0
        previous_was_digit = False
    return total + group


# --- Dates --------------------------------------------------------------------------------------

_MONTHS = {
    "januari": 1, "jan": 1,
    "februari": 2, "feb": 2, "pebruari": 2, "peb": 2,
    "maret": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "agustus": 8, "agu": 8, "agt": 8, "ags": 8, "agus": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11, "nop": 11,
    "desember": 12, "des": 12,
}  # fmt: skip
_WEEKDAYS = {
    "senin": 0,
    "selasa": 1,
    "rabu": 2,
    "kamis": 3,
    "jumat": 4,
    "jum'at": 4,
    "sabtu": 5,
    "minggu": 6,
    "ahad": 6,
}
_TODAY_WORDS = {"hari ini", "sekarang", "barusan", "tadi", "tadi pagi", "tadi siang", "tadi sore"}
_DATE_PREFIX = re.compile(r"^(tgl\.?|tanggal|hari)\s+")
_DAY_MONTH = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2}|\d{4}))?$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NAMED = re.compile(r"^(\d{1,2}) ([a-z]+)(?: (\d{4}))?$")
_AGO = re.compile(r"^(.+?) (hari|minggu) (?:yang )?lalu$")


def today_in(time_zone: str) -> dt.date:
    """Today's date where the workspace is (default Asia/Jakarta)."""
    return dt.datetime.now(ZoneInfo(time_zone)).date()


def parse_date(text: str, *, today: dt.date) -> dt.date | None:
    """ "kemarin", "2 hari lalu", "senin", "12/11", "12 nov 2026" → a date on or before today.
    Reports describe the past: a day-month that would be in the future means last year."""
    t = normalize(text)
    if t in _TODAY_WORDS:
        return today
    t = _DATE_PREFIX.sub("", t)
    if t == "kemarin":
        return today - dt.timedelta(days=1)
    if t in ("kemarin lusa", "lusa kemarin"):
        return today - dt.timedelta(days=2)
    if t in ("seminggu lalu", "seminggu yang lalu"):
        return today - dt.timedelta(days=7)
    if m := _AGO.match(t):
        count = parse_number(m.group(1))
        if count is None or count.unit or count.value != count.value.to_integral_value():
            return None
        days = int(count.value) * (7 if m.group(2) == "minggu" else 1)
        return today - dt.timedelta(days=days) if 0 <= days <= 366 else None
    weekday = t.removesuffix(" lalu").removesuffix(" kemarin")
    if weekday in _WEEKDAYS:
        return today - dt.timedelta(days=(today.weekday() - _WEEKDAYS[weekday]) % 7)
    if m := _ISO.match(t):
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _DAY_MONTH.match(t):
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        if year is None:
            return _past(day, month, today)
        full_year = int(year) + (2000 if len(year) == 2 else 0)
        return _date(full_year, month, day)
    if m := _NAMED.match(t):
        month = _MONTHS.get(m.group(2))
        if month is None:
            return None
        day = int(m.group(1))
        return _date(int(m.group(3)), month, day) if m.group(3) else _past(day, month, today)
    return None


def _date(year: int, month: int, day: int) -> dt.date | None:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def _past(day: int, month: int, today: dt.date) -> dt.date | None:
    this_year = _date(today.year, month, day)
    if this_year is None or this_year <= today:
        return this_year
    return _date(today.year - 1, month, day)


# --- Choices ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """One option offered: the stored value, the label shown, other words that mean it."""

    value: str
    label: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChoiceMatch:
    value: str
    label: str
    # True for a fuzzy guess ("pdi" → Padi): confirm before saving.
    needs_confirmation: bool = False


@dataclass(frozen=True)
class MultiChoiceResult:
    matches: list[ChoiceMatch] = field(default_factory=list)
    # Parts of the answer that matched nothing, as typed.
    unknown: list[str] = field(default_factory=list)


# Words that may surround a choice without changing it ("sehat semua", "terserang hama").
_CHOICE_FILLERS = {
    "ya", "saja", "aja", "semua", "sekali", "banget", "kok", "deh", "nih", "dong", "sih",
    "yang", "itu", "pak", "bu", "kak", "mas", "mbak", "hama", "penyakit",
}  # fmt: skip
_INDEX = re.compile(r"^(?:no\.?|nomor|pilihan|opsi)?\s*(\d{1,2})$")
_FUZZY_MIN = 80.0
_FUZZY_MARGIN = 5.0


def parse_choice(text: str, options: Sequence[Choice]) -> ChoiceMatch | None:
    """Match an answer to one option: by its number in the list, exactly (label, value, alias),
    inside a short phrase ("sehat semua"), or by a close spelling that needs confirming."""
    t = normalize(text)
    if not t or not options:
        return None
    if m := _INDEX.match(t):
        index = int(m.group(1))
        return _match(options[index - 1]) if 1 <= index <= len(options) else None
    words = [w for w in t.split() if w not in _CHOICE_FILLERS] or t.split()
    core = " ".join(words)
    phrases = [(p, o) for o in options for p in _phrases(o)]

    exact = {o.value: o for p, o in phrases if p == core}
    if len(exact) == 1:
        return _match(next(iter(exact.values())))

    # A known phrase inside the answer, the rest being filler words only.
    found: dict[str, tuple[int, Choice]] = {}
    for phrase, option in phrases:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", t):
            leftover = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", t).split()
            if all(w in _CHOICE_FILLERS for w in leftover):
                length = len(phrase)
                if length > found.get(option.value, (0, option))[0]:
                    found[option.value] = (length, option)
    if found:
        best = max(length for length, _ in found.values())
        winners = [o for length, o in found.values() if length == best]
        return _match(winners[0]) if len(winners) == 1 else None

    # Typos: close to exactly one option.
    scored: dict[str, tuple[float, Choice]] = {}
    for phrase, option in phrases:
        score = fuzz.ratio(core, phrase)
        if score > scored.get(option.value, (0.0, option))[0]:
            scored[option.value] = (score, option)
    ranked = sorted(scored.values(), key=lambda s: s[0], reverse=True)
    if not ranked or ranked[0][0] < _FUZZY_MIN:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < _FUZZY_MARGIN:
        return None
    return _match(ranked[0][1], needs_confirmation=True)


_SPLIT = re.compile(r"\s*(?:,|;|/|&|\bdan\b|\bserta\b)\s*")


def parse_multi_choice(text: str, options: Sequence[Choice]) -> MultiChoiceResult:
    """ "padi, jagung dan cabai" → each option once, plus the parts nothing matched."""
    matches: list[ChoiceMatch] = []
    unknown: list[str] = []
    for part in (p.strip() for p in _SPLIT.split(normalize(text))):
        if not part:
            continue
        match = parse_choice(part, options)
        if match is None:
            unknown.append(part)
        elif all(m.value != match.value for m in matches):
            matches.append(match)
    return MultiChoiceResult(matches, unknown)


def _phrases(option: Choice) -> list[str]:
    return [
        normalize(p)
        for p in (option.label, option.value.replace("_", " "), *option.aliases)
        if normalize(p)
    ]


def _match(option: Choice, *, needs_confirmation: bool = False) -> ChoiceMatch:
    return ChoiceMatch(option.value, option.label, needs_confirmation)


# --- Yes / no -----------------------------------------------------------------------------------

_YES = {"ya", "iya", "iyaa", "y", "yes", "ok", "oke", "okay", "betul", "benar", "sudah", "udah",
        "siap", "boleh", "setuju", "lanjut"}  # fmt: skip
_NO = {"tidak", "tdk", "gak", "ga", "nggak", "ngga", "enggak", "engga", "no", "n", "belum",
       "blm", "bukan", "jangan", "batal"}  # fmt: skip


def parse_yes_no(text: str) -> bool | None:
    words = normalize(text).split()
    if not words:
        return None
    if all(w in _YES for w in words):
        return True
    if all(w in _NO for w in words):
        return False
    return None
