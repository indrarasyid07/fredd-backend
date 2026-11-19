"""The worker process imports only app.worker; every table must still be known there, or a
job touching a table with foreign keys fails (tests load all models, so check in a fresh
interpreter)."""

import subprocess
import sys

CHECK = (
    "import app.worker\n"
    "from app.db.base import Base\n"
    "assert 'workspaces' in {t.name for t in Base.metadata.sorted_tables}\n"
)


def test_worker_loads_every_table() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CHECK], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr[-500:]
