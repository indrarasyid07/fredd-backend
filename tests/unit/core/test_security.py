from app.core.security import hash_password, hash_token, new_token, verify_password


def test_password_round_trip() -> None:
    hashed = hash_password("rahasia123")
    assert hashed.startswith("$argon2id$")
    assert verify_password("rahasia123", hashed)
    assert not verify_password("salah123", hashed)


def test_missing_hash_never_verifies() -> None:
    # Google-only accounts and unknown emails have no hash; even the dummy's own secret must fail.
    assert not verify_password("timing-equaliser-not-a-real-password", None)
    assert not verify_password("anything", None)


def test_garbage_hash_does_not_raise() -> None:
    assert not verify_password("rahasia123", "not-a-hash")


def test_tokens_are_random_and_hash_is_stable() -> None:
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40
    assert hash_token(a) == hash_token(a)
    assert len(hash_token(a)) == 64
