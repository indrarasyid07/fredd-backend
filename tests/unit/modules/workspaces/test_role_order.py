import pytest

from app.modules.workspaces.service import role_at_least


@pytest.mark.parametrize(
    ("role", "min_role", "allowed"),
    [
        ("reviewer", "reviewer", True),
        ("reviewer", "form_editor", False),
        ("reviewer", "admin", False),
        ("form_editor", "reviewer", True),
        ("form_editor", "form_editor", True),
        ("form_editor", "admin", False),
        ("admin", "reviewer", True),
        ("admin", "admin", True),
    ],
)
def test_role_order(role: str, min_role: str, allowed: bool) -> None:
    assert role_at_least(role, min_role) is allowed  # type: ignore[arg-type]
