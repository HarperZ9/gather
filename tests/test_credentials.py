import pytest

from gather.credentials import MissingCredential, has_secret, require_secret


def test_require_secret_returns_the_env_value(monkeypatch):
    monkeypatch.setenv("GATHER_TEST_SECRET", "s3cr3t")
    assert require_secret("GATHER_TEST_SECRET") == "s3cr3t"
    assert has_secret("GATHER_TEST_SECRET") is True


def test_require_secret_raises_without_revealing_anything(monkeypatch):
    monkeypatch.delenv("GATHER_TEST_SECRET", raising=False)
    with pytest.raises(MissingCredential) as exc:
        require_secret("GATHER_TEST_SECRET")
    assert "GATHER_TEST_SECRET" in str(exc.value)   # the message names the var, not a value
    assert has_secret("GATHER_TEST_SECRET") is False


def test_empty_credential_counts_as_missing(monkeypatch):
    monkeypatch.setenv("GATHER_TEST_SECRET", "")
    assert has_secret("GATHER_TEST_SECRET") is False
    with pytest.raises(MissingCredential):
        require_secret("GATHER_TEST_SECRET")


def test_has_secret_matches_require_secret_on_whitespace_and_newlines(monkeypatch):
    # a presence check used for planning must agree with the gate that actually
    # runs: a whitespace-only or newline-bearing value is NOT usable
    monkeypatch.setenv("GATHER_TEST_SECRET", "   ")
    assert has_secret("GATHER_TEST_SECRET") is False
    monkeypatch.setenv("GATHER_TEST_SECRET", "tok\nen")
    assert has_secret("GATHER_TEST_SECRET") is False
    monkeypatch.setenv("GATHER_TEST_SECRET", "real-token")
    assert has_secret("GATHER_TEST_SECRET") is True
