"""``secrets.py`` against in-memory and deliberately broken keyring backends.
Never the machine's real keyring: ``conftest.py`` installs an in-memory one
for every test, and the tests here swap it for the "none" and "failing"
cases."""

from __future__ import annotations

from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail, null

from sensei_top import secrets


class _Raising(KeyringBackend):
    priority = 1

    def get_password(self, service, username):
        raise RuntimeError("locked")

    def set_password(self, service, username, password):
        raise RuntimeError("locked")

    def delete_password(self, service, username):
        raise RuntimeError("locked")


def test_set_get_delete_round_trip():
    assert secrets.get(secrets.CLAUDE) is None
    assert secrets.set(secrets.CLAUDE, "k1") is True
    assert secrets.get(secrets.CLAUDE) == "k1"
    assert secrets.get(secrets.TOPDECK) is None
    assert secrets.delete(secrets.CLAUDE) is True
    assert secrets.get(secrets.CLAUDE) is None


def test_values_are_stored_under_the_sensei_top_service(memory_keyring):
    secrets.set(secrets.TOPDECK, "t1")
    assert memory_keyring == {("sensei-top", "topdeck"): "t1"}


def test_deleting_an_unset_key_is_not_a_failure(caplog):
    with caplog.at_level("WARNING"):
        assert secrets.delete(secrets.CLAUDE) is True
    assert caplog.messages == []


def test_a_delete_error_on_a_stored_key_is_a_failure(memory_keyring, caplog):
    class _StuckDelete(type(keyring.get_keyring())):
        def delete_password(self, service, username):
            from keyring.errors import PasswordDeleteError

            raise PasswordDeleteError("Cancelled by user")

    backend = _StuckDelete()
    backend.store = memory_keyring
    keyring.set_keyring(backend)
    secrets.set(secrets.CLAUDE, "k")
    with caplog.at_level("WARNING"):
        assert secrets.delete(secrets.CLAUDE) is False
    assert len(caplog.messages) == 1
    assert secrets.get(secrets.CLAUDE) == "k"


def test_backend_name_reports_the_active_backend():
    assert secrets.backend_name() is not None


@pytest.mark.parametrize("backend_cls", [fail.Keyring, null.Keyring])
def test_fail_and_null_backends_mean_no_backend_silently(backend_cls, caplog):
    keyring.set_keyring(backend_cls())
    with caplog.at_level("WARNING"):
        assert secrets.backend_name() is None
        assert secrets.get(secrets.CLAUDE) is None
        assert secrets.set(secrets.CLAUDE, "k") is False
        assert secrets.delete(secrets.CLAUDE) is False
    assert caplog.messages == []


def test_a_backend_error_warns_and_reads_as_nothing_stored(caplog):
    keyring.set_keyring(_Raising())
    with caplog.at_level("WARNING"):
        assert secrets.get(secrets.CLAUDE) is None
        assert secrets.set(secrets.CLAUDE, "secret-value") is False
        assert secrets.delete(secrets.CLAUDE) is False
    assert len(caplog.messages) == 3
    assert all("locked" in m for m in caplog.messages)
    assert not any("secret-value" in m for m in caplog.messages)


def test_the_module_imports_nothing_from_llm():
    import sensei_top.secrets as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "sensei_top.llm" not in source.replace("llm/config.py", "")
