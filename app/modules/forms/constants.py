from typing import Literal

FormStatus = Literal["draft", "pilot", "active", "archived"]
FORM_STATUSES: tuple[FormStatus, ...] = ("draft", "pilot", "active", "archived")

# The 12 field kinds of the wizard's type picker, in its order.
FieldType = Literal[
    "short_text",
    "long_text",
    "number",
    "single_choice",
    "multi_choice",
    "datetime",
    "location",
    "photo",
    "video",
    "voice",
    "document",
    "signature",
]

# What a field means to the dashboard: `condition` feeds reports.condition, `area` feeds
# reports.area_ha. At most one field per role in a definition.
FieldRole = Literal["condition", "area"]

# Crop condition values (D2, B-052). Labels (Sehat / Perlu perhatian / Terserang) live in the UI.
CONDITION_VALUES = ("healthy", "attention", "infected")

# Ways an answer may arrive in chat, switched on per field in the wizard.
AnswerMode = Literal[
    "type",  # typed text
    "voice",  # voice note, transcribed
    "range",  # number picked from a range
    "choose",  # tap one of the options
    "pick",  # date picker
    "name",  # location typed as a place name
    "map",  # location shared from the map
    "live",  # live location
    "send",  # media sent from the gallery
    "camera",  # media taken with the camera
    "photo",  # document sent as a photo
    "file",  # document uploaded as a file
    "draw",  # signature drawn on screen
]

ANSWER_MODES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "short_text": ("type", "voice"),
    "long_text": ("type", "voice"),
    "number": ("type", "range", "voice"),
    "single_choice": ("type", "choose", "voice"),
    "multi_choice": ("type", "choose", "voice"),
    "datetime": ("type", "pick"),
    "location": ("name", "map", "live", "voice"),
    "photo": ("send", "camera"),
    "video": ("send", "camera"),
    "voice": ("send",),
    "document": ("photo", "file"),
    "signature": ("draw",),
}

CHOICE_TYPES = ("single_choice", "multi_choice")
MEDIA_TYPES = ("photo", "video", "document")
# Types where `min`/`max` apply: the value itself (number) or how many answers (choices, media).
BOUNDED_TYPES = ("number", "multi_choice", *MEDIA_TYPES)

MAX_FIELDS = 50
MAX_OPTIONS = 30
MAX_RULES = 50
