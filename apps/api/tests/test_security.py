from tutor_api.core.security import hash_password, verify_password


def test_password_hash_never_equals_plaintext() -> None:
    password = "Correct horse battery staple 9"

    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash)
    assert not verify_password("wrong password", password_hash)
