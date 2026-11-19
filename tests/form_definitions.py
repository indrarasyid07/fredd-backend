"""Sample FormDefinition data for tests of any domain (conversation engine, reports, ...)."""

from typing import Any


def crop_survey() -> dict[str, Any]:
    """The "Survei Kondisi Tanaman" starter of the wizard, as a definition."""
    condition = [("healthy", "Sehat"), ("attention", "Perlu perhatian"), ("infected", "Terserang")]
    return {
        "fields": [
            {
                "key": "location",
                "type": "location",
                "label": "Lokasi lahan",
                "question": "Di mana lahan yang dikunjungi hari ini?",
                "max_accuracy_m": 50,
            },
            {
                "key": "farmer_name",
                "type": "short_text",
                "label": "Nama petani",
                "question": "Siapa nama petani pemilik lahan?",
            },
            {
                "key": "land_area",
                "type": "number",
                "label": "Luas lahan",
                "question": "Berapa luas lahannya?",
                "unit": "ha",
                "min": 0,
                "max": 500,
                "review_above": 50,
                "role": "area",
            },
            {
                "key": "condition",
                "type": "single_choice",
                "label": "Kondisi tanaman",
                "question": "Bagaimana kondisi tanamannya?",
                "role": "condition",
                "options": [{"value": v, "label": label} for v, label in condition],
                "answer_modes": ["choose", "type"],
            },
            {
                "key": "photos",
                "type": "photo",
                "label": "Foto lahan",
                "question": "Boleh kirim 1 sampai 3 foto lahannya?",
                "required": False,
                "min": 1,
                "max": 3,
            },
        ],
        "rules": [
            {"if": {"field": "condition", "equals": "infected"}, "then": {"require": "photos"}},
            {"if": {"field": "land_area", "equals": 0}, "then": {"needs_review": True}},
        ],
    }
