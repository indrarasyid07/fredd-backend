"""Indonesian answer parsers (roadmap 3.2). Written before the parsers: this is where chat
answers most often go wrong, and a wrong number in a field report is worse than asking again."""

import datetime as dt
from decimal import Decimal

import pytest
import time_machine
from hypothesis import given
from hypothesis import strategies as st

from app.modules.conversations.engine.parsers import (
    Choice,
    parse_choice,
    parse_date,
    parse_multi_choice,
    parse_number,
    parse_yes_no,
    today_in,
)

# --- Numbers ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("1,5", "1.5", None),
        ("1.5", "1.5", None),
        ("15", "15", None),
        ("0,25", "0.25", None),
        ("1.500", "1500", None),  # dot + 3 digits = thousands
        ("1.250.000", "1250000", None),
        ("1.500,75", "1500.75", None),
        ("Rp 1.250.000", "1250000", "rupiah"),
        ("Rp1.250.000,-", "1250000", "rupiah"),
        ("2 ha", "2", "ha"),
        ("2ha", "2", "ha"),
        ("sekitar 2 hektar", "2", "ha"),
        ("kira-kira 2,5 hektare", "2.5", "ha"),
        ("3 kw", "3", "quintal"),
        ("40 kg", "40", "kg"),
        ("12 orang", "12", "person"),
        ("satu setengah", "1.5", None),
        ("setengah", "0.5", None),
        ("seperempat hektar", "0.25", "ha"),
        ("dua koma lima", "2.5", None),
        ("dua ratus lima puluh", "250", None),
        ("seratus", "100", None),
        ("sebelas", "11", None),
        ("tujuh belas", "17", None),
        ("dua ribu tiga ratus", "2300", None),
        ("satu juta dua ratus ribu", "1200000", None),
        ("1/2", "0.5", None),
        ("3/4 ha", "0.75", "ha"),
        ("1 1/2", "1.5", None),
        ("lima", "5", None),
        ("Lima Hektar.", "5", "ha"),
        ("nol", "0", None),
        ("-3", "-3", None),
        ("25°C", "25", "celsius"),
    ],
)
def test_numbers(text: str, value: str, unit: str | None) -> None:
    parsed = parse_number(text)
    assert parsed is not None, text
    assert parsed.value == Decimal(value), text
    assert parsed.unit == unit, text


@pytest.mark.parametrize(
    "text",
    ["banyak", "", "   ", "lumayan luas", "1-2", "2 atau 3", "1,5,6", "dua tiga", "abc 5 def 6"],
)
def test_not_a_number(text: str) -> None:
    assert parse_number(text) is None, text


def test_units_from_reference_data_aliases() -> None:
    units = {"tumbak": "tumbak", "bata": "bata"}
    parsed = parse_number("40 tumbak", units=units)
    assert parsed is not None and (parsed.value, parsed.unit) == (Decimal(40), "tumbak")


@given(st.integers(min_value=0, max_value=10**9))
def test_any_integer_with_thousand_dots(n: int) -> None:
    text = f"{n:,}".replace(",", ".")
    parsed = parse_number(text)
    assert parsed is not None and parsed.value == n


@given(st.integers(min_value=0, max_value=99_999), st.integers(min_value=1, max_value=99))
def test_any_decimal_with_comma(whole: int, cents: int) -> None:
    text = f"{whole},{cents:02d}"
    parsed = parse_number(text)
    assert parsed is not None and parsed.value == Decimal(f"{whole}.{cents:02d}")


# --- Dates --------------------------------------------------------------------------------------

TODAY = dt.date(2026, 11, 19)  # a Thursday


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hari ini", TODAY),
        ("sekarang", TODAY),
        ("tadi pagi", TODAY),
        ("kemarin", dt.date(2026, 11, 18)),
        ("kemarin lusa", dt.date(2026, 11, 17)),
        ("2 hari lalu", dt.date(2026, 11, 17)),
        ("tiga hari yang lalu", dt.date(2026, 11, 16)),
        ("seminggu lalu", dt.date(2026, 11, 12)),
        ("senin", dt.date(2026, 11, 16)),
        ("senin lalu", dt.date(2026, 11, 16)),
        ("kamis", TODAY),
        ("hari jumat", dt.date(2026, 11, 13)),
        ("12/11", dt.date(2026, 11, 12)),
        ("12-11", dt.date(2026, 11, 12)),
        ("12/11/2026", dt.date(2026, 11, 12)),
        ("12/11/26", dt.date(2026, 11, 12)),
        ("2026-11-12", dt.date(2026, 11, 12)),
        ("12 nov", dt.date(2026, 11, 12)),
        ("12 November 2026", dt.date(2026, 11, 12)),
        ("tgl 3 agustus", dt.date(2026, 8, 3)),
        ("28/12", dt.date(2025, 12, 28)),  # a future day this year means last year
        ("1 Jan", dt.date(2026, 1, 1)),
    ],
)
def test_dates(text: str, expected: dt.date) -> None:
    assert parse_date(text, today=TODAY) == expected, text


@pytest.mark.parametrize("text", ["", "minggu depan", "31/02", "13/13", "kapan-kapan", "32 nov"])
def test_not_a_date(text: str) -> None:
    assert parse_date(text, today=TODAY) is None, text


@given(st.dates(min_value=dt.date(2000, 1, 1), max_value=dt.date(2099, 12, 31)))
def test_any_full_date(day: dt.date) -> None:
    assert parse_date(f"{day.day}/{day.month}/{day.year}", today=TODAY) == day
    assert parse_date(day.isoformat(), today=TODAY) == day


def test_today_follows_the_workspace_time_zone() -> None:
    # 17:30 UTC on the 19th is already 00:30 on the 20th in Jakarta, still the 19th in Pacific.
    with time_machine.travel(dt.datetime(2026, 11, 19, 17, 30, tzinfo=dt.UTC), tick=False):
        assert today_in("Asia/Jakarta") == dt.date(2026, 11, 20)
        assert today_in("Asia/Jayapura") == dt.date(2026, 11, 20)
        assert today_in("UTC") == dt.date(2026, 11, 19)


# --- Choices ------------------------------------------------------------------------------------

COMMODITIES = [
    Choice("rice", "Padi", aliases=("pari", "gabah", "padi sawah")),
    Choice("corn", "Jagung", aliases=("jagong",)),
    Choice("chili", "Cabai merah", aliases=("cabe", "cabai", "lombok")),
    Choice("bird_chili", "Cabai rawit", aliases=("cengek", "rawit")),
    Choice("cassava", "Ubi kayu", aliases=("singkong", "sampeu")),
]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Padi", "rice"),
        ("padi", "rice"),
        ("  PADI.  ", "rice"),
        ("pari", "rice"),
        ("rice", "rice"),
        ("sampeu", "cassava"),
        ("Cabai rawit", "bird_chili"),
        ("cabe", "chili"),
        ("2", "corn"),  # number of the option in the list shown
        ("no 2", "corn"),
        ("ubi kayu ya", "cassava"),
    ],
)
def test_choice_exact(text: str, value: str) -> None:
    match = parse_choice(text, COMMODITIES)
    assert match is not None, text
    assert (match.value, match.needs_confirmation) == (value, False), text


@pytest.mark.parametrize(
    ("text", "value"), [("pdi", "rice"), ("jagnug", "corn"), ("singkon", "cassava")]
)
def test_choice_typo_needs_confirmation(text: str, value: str) -> None:
    match = parse_choice(text, COMMODITIES)
    assert match is not None, text
    assert (match.value, match.needs_confirmation) == (value, True), text


@pytest.mark.parametrize("text", ["", "kopi", "9", "0", "cabai apa saja", "xyz"])
def test_choice_no_match(text: str) -> None:
    assert parse_choice(text, COMMODITIES) is None, text


def test_condition_labels() -> None:
    options = [
        Choice("healthy", "Sehat"),
        Choice("attention", "Perlu perhatian"),
        Choice("infected", "Terserang"),
    ]
    assert parse_choice("perlu perhatian", options).value == "attention"  # type: ignore[union-attr]
    assert parse_choice("terserang hama", options).value == "infected"  # type: ignore[union-attr]
    assert parse_choice("sehat semua", options).value == "healthy"  # type: ignore[union-attr]


def test_multi_choice() -> None:
    result = parse_multi_choice("padi, jagung dan cengek", COMMODITIES)
    assert [m.value for m in result.matches] == ["rice", "corn", "bird_chili"]
    assert result.unknown == []

    result = parse_multi_choice("padi dan kopi", COMMODITIES)
    assert [m.value for m in result.matches] == ["rice"]
    assert result.unknown == ["kopi"]

    result = parse_multi_choice("1, 3", COMMODITIES)
    assert [m.value for m in result.matches] == ["rice", "chili"]

    result = parse_multi_choice("padi, pari", COMMODITIES)
    assert [m.value for m in result.matches] == ["rice"]  # duplicates collapse


# --- Yes / no -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["ya", "Iya", "y", "ok", "oke", "betul", "benar", "sudah", "siap", "yes"]
)
def test_yes(text: str) -> None:
    assert parse_yes_no(text) is True


@pytest.mark.parametrize(
    "text", ["tidak", "tdk", "gak", "nggak", "enggak", "ga", "no", "belum", "bukan"]
)
def test_no(text: str) -> None:
    assert parse_yes_no(text) is False


@pytest.mark.parametrize("text", ["", "mungkin", "ya tidak", "nanti"])
def test_neither(text: str) -> None:
    assert parse_yes_no(text) is None
