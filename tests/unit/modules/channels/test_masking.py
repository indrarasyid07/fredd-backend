from app.modules.channels.masking import mask_chat_id, mask_phone


def test_phone_keeps_country_prefix_and_last_four() -> None:
    assert mask_phone("+6281100001234") == "+62 811-****-1234"
    assert mask_phone("+62811") == "****"


def test_chat_id_keeps_last_four() -> None:
    assert mask_chat_id("123456789") == "•••6789"
    assert mask_chat_id("123") == "••••"
