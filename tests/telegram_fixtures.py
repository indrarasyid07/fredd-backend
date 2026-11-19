import json
from pathlib import Path
from typing import Any

_DIR = Path(__file__).parent / "fixtures" / "webhooks" / "telegram"


def telegram_update(name: str, **changes: Any) -> dict[str, Any]:
    """A fixture update; `update_id=` and top-level changes override it."""
    data = json.loads((_DIR / f"{name}.json").read_text())
    data.update(changes)
    return data
