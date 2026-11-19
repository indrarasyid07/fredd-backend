from app.modules.join_codes.constants import ALPHABET
from app.modules.join_codes.service import display, new_code


def test_codes_avoid_look_alikes_and_show_with_a_dash() -> None:
    codes = {new_code() for _ in range(500)}
    assert len(codes) == 500  # random, not derived from anything
    for code in codes:
        assert len(code) == 8 and set(code) <= set(ALPHABET)
        assert not set(code) & set("ILOU01")
    assert display("K7M29QXA") == "K7M2-9QXA"
