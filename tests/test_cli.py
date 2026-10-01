"""Tests for the CLI's own loopback gate -- ``_require_loopback`` and its
wiring into ``cmd_serve`` (AGENTS.md non-negotiable #5: "Loopback binds
only ... this is why no part of this app needs an authentication story").

The CLI-level test never binds a real socket: it monkeypatches every
function ``cmd_serve`` would reach past ``_require_loopback`` (``_open``,
``_build_watcher_process``, ``_start_archetype_refresh``,
``_start_reference_refresh``, ``_start_backup``, ``uvicorn.run``) to raise if
called at all, so a regression that let a bad host slip past the gate would
fail loudly here rather than actually starting a server.
"""

from __future__ import annotations

import pytest
import uvicorn

from sensei_top import cli as cli_module

# --- _require_loopback, direct ---------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_require_loopback_accepts_loopback_addresses(host):
    cli_module._require_loopback(host)  # must not raise


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "example.com"])
def test_require_loopback_rejects_everything_else(host):
    with pytest.raises(SystemExit):
        cli_module._require_loopback(host)


def test_require_loopback_message_names_the_offending_host_and_the_reason():
    with pytest.raises(SystemExit) as exc_info:
        cli_module._require_loopback("0.0.0.0")
    message = str(exc_info.value)
    assert "0.0.0.0" in message
    assert "loopback" in message
    assert "AGENTS.md non-negotiable #5" in message


# --- cmd_serve, CLI level ---------------------------------------------------


def _refuse_to_start(name: str):
    def _raise(*args, **kwargs):
        raise AssertionError(f"{name} must not be called: _require_loopback should exit first")
    return _raise


def test_serve_with_a_non_loopback_host_exits_before_anything_starts(monkeypatch, tmp_path):
    for target in (
        "_open", "_build_watcher_process", "_start_archetype_refresh",
        "_start_reference_refresh", "_start_backup",
    ):
        monkeypatch.setattr(cli_module, target, _refuse_to_start(target))
    monkeypatch.setattr(uvicorn, "run", _refuse_to_start("uvicorn.run"))

    parser = cli_module.build_parser()
    args = parser.parse_args(
        ["--db", str(tmp_path / "t.db"), "serve", "--host", "0.0.0.0"]
    )

    with pytest.raises(SystemExit):
        cli_module.cmd_serve(args)


def test_serve_with_an_ipv6_loopback_host_passes_the_gate(monkeypatch, tmp_path):
    """``::1`` must clear ``_require_loopback`` -- this test only proves the
    gate lets it through (the next thing ``cmd_serve`` does, since the
    database doesn't exist yet and ``--watch`` wasn't passed, is its own
    unrelated ``sys.exit`` -- never a bound socket)."""
    parser = cli_module.build_parser()
    args = parser.parse_args(
        ["--db", str(tmp_path / "t.db"), "serve", "--host", "::1"]
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_module.cmd_serve(args)
    assert "No database at" in str(exc_info.value)  # never reached the loopback message
