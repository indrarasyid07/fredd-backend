"""Write openapi.json, the API contract the frontend generates its types from.

uv run python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).parents[1] / "openapi.json"

if __name__ == "__main__":
    OUTPUT.write_text(
        json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf8"
    )
    print(f"Wrote {OUTPUT.name}")
