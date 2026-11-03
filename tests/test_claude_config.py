"""Tests for the Claude credential and the config file around it:
``claude_config.py`` (resolution order, ``load_coach()``, ``key_source()``),
the ``config`` subcommand's writers, ``mtgo/config.py``'s ``resolve_log_dir()``
and ``config_path()`` on Windows.

No test here makes a network call or touches a real key: each runs against
real env vars, a scratch config file and an in-memory keyring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sensei_top import claude_config as llm_config_module
from sensei_top import cli as cli_module
from sensei_top import config as config_module
from sensei_top.claude_config import LLMConfig, load

# --- claude_config.py: credential resolution -------------------------------


def _write_config(
    tmp_path: Path, *, api_key: str, model: str | None = None, effort: str | None = None
):
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir(exist_ok=True)
    lines = ["[claude]", f'api_key = "{api_key}"']
    if model:
        lines.append(f'model = "{model}"')
    if effort:
        lines.append(f'effort = "{effort}"')
    (config_dir / "config.toml").write_text("\n".join(lines) + "\n")


def test_nothing_configured_yields_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def test_env_key_wins_but_the_file_still_supplies_model_and_effort(monkeypatch, tmp_path):
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="low")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

    cfg = load()
    assert cfg == LLMConfig(api_key="env-key", model="claude-sonnet-5", effort="low")


def test_env_key_alone_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    cfg = load()
    assert cfg == LLMConfig(api_key="env-key", model="claude-opus-5-5", effort="high")


def test_the_config_file_alone_is_enough(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="medium")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() == LLMConfig(api_key="file-key", model="claude-sonnet-5", effort="medium")


def test_malformed_toml_yields_none_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not { valid toml at all")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def _write_latin1_config(tmp_path):
    """A config file saved in Latin-1 rather than UTF-8 — what an editor
    that defaults to the system code page writes for an accented value.
    ``tomllib`` raises ``UnicodeDecodeError`` on it, not ``TOMLDecodeError``."""
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    path = config_dir / "config.toml"
    path.write_bytes(
        '[claude]\napi_key = "file-key"\n[mtgo]\nhandle = "Jos\xe9"\n'
        '[arena]\nlog = "/tmp/Player.log"\n[backup]\nkeep = "3"\n'
        '[topdeck]\napi_key = "td-key"\n'.encode("latin-1")
    )
    return path


def test_a_non_utf8_file_is_unreadable_for_every_reader_not_an_exception(monkeypatch, tmp_path):
    from sensei_top import arena_config, diagnostics
    from sensei_top.backup import config as backup_config
    from sensei_top.metagame import config as topdeck_config
    from sensei_top.mtgo import config as mtgo_config

    path = _write_latin1_config(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert load() is None
    assert llm_config_module.load_coach() is None
    assert mtgo_config.load_handle() is None
    assert arena_config.load_log() is None
    assert topdeck_config.load() is None
    assert backup_config.resolve(tmp_path / "sensei-top.db").keep_source == "default"
    assert diagnostics.secret_free_config(path) is None
    assert cli_module._read_config_tables() == {}


def test_a_file_with_no_claude_table_yields_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[other]\nfoo = "bar"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def test_a_missing_file_yields_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def test_keyring_beats_the_file_but_not_the_environment(monkeypatch, tmp_path, memory_keyring):
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="low")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    memory_keyring[("sensei-top", "claude")] = "keyring-key"

    assert load() == LLMConfig(api_key="keyring-key", model="claude-sonnet-5", effort="low")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert load() == LLMConfig(api_key="env-key", model="claude-sonnet-5", effort="low")


def test_a_keyring_key_alone_is_enough_with_default_model(memory_keyring):
    memory_keyring[("sensei-top", "claude")] = "keyring-key"
    assert load() == LLMConfig(api_key="keyring-key")


def test_a_keyring_key_with_a_file_lacking_claude_warns_nothing(
    monkeypatch, tmp_path, memory_keyring, caplog
):
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[topdeck]\napi_key = "t"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    memory_keyring[("sensei-top", "claude")] = "keyring-key"
    with caplog.at_level("WARNING"):
        assert load() == LLMConfig(api_key="keyring-key")
    assert caplog.messages == []


def test_the_topdeck_entry_is_not_a_claude_credential(memory_keyring):
    memory_keyring[("sensei-top", "topdeck")] = "topdeck-key"
    assert load() is None


def test_a_failing_keyring_falls_back_to_the_file_with_a_warning(monkeypatch, tmp_path, caplog):
    import keyring
    from keyring.backend import KeyringBackend

    class Raising(KeyringBackend):
        priority = 1

        def get_password(self, service, username):
            raise RuntimeError("locked")

        def set_password(self, service, username, password):
            raise RuntimeError("locked")

        def delete_password(self, service, username):
            raise RuntimeError("locked")

    keyring.set_keyring(Raising())
    _write_config(tmp_path, api_key="file-key")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with caplog.at_level("WARNING"):
        assert load() == LLMConfig(api_key="file-key")
    assert any("keyring" in m for m in caplog.messages)


def test_no_keyring_backend_falls_back_to_the_file_silently(monkeypatch, tmp_path, caplog):
    import keyring
    from keyring.backends import fail

    keyring.set_keyring(fail.Keyring())
    _write_config(tmp_path, api_key="file-key")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with caplog.at_level("WARNING"):
        assert load() == LLMConfig(api_key="file-key")
    assert caplog.messages == []


def test_topdeck_resolution_order_is_environment_keyring_file(
    monkeypatch, tmp_path, memory_keyring
):
    from sensei_top.metagame import config as topdeck_config_module

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[topdeck]\napi_key = "file-key"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert topdeck_config_module.load().api_key == "file-key"
    memory_keyring[("sensei-top", "topdeck")] = "keyring-key"
    assert topdeck_config_module.load().api_key == "keyring-key"
    monkeypatch.setenv("TOPDECK_API_KEY", "env-key")
    assert topdeck_config_module.load().api_key == "env-key"


# --- claude_config.py: load_coach() ------------------------------------------


def test_load_coach_applies_overrides_while_load_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[claude]\n"
        'api_key = "file-key"\n'
        'model = "claude-opus-5"\n'
        'effort = "high"\n'
        "\n"
        "[claude.coach]\n"
        'model = "claude-fable-5-1"\n'
        'effort = "max"\n'
        "web_search = false\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    base = llm_config_module.load()
    assert base == LLMConfig(api_key="file-key", model="claude-opus-5", effort="high")
    assert base.web_search is True

    coach = llm_config_module.load_coach()
    assert coach == LLMConfig(
        api_key="file-key", model="claude-fable-5-1", effort="max", web_search=False
    )

    # load() itself must come back unchanged by the coach table existing.
    assert llm_config_module.load() == base


def test_load_coach_with_no_coach_table_falls_back_to_the_base_config(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="low")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert llm_config_module.load_coach() == LLMConfig(
        api_key="file-key", model="claude-sonnet-5", effort="low"
    )


# --- cli.py: the config subcommand's [claude.coach] table -----------------


def _seed_coach_table(config_home):
    """No command writes ``[claude.coach]``; a user edits the file by hand."""
    path = config_home / "sensei-top" / "config.toml"
    with path.open("a") as handle:
        handle.write(
            '\n[claude.coach]\nmodel = "claude-fable-5-1"\neffort = "max"\n'
            "web_search = false\n"
        )


def test_write_llm_config_round_trips_the_coach_table_and_preserves_other_keys(
    monkeypatch, tmp_path
):
    """Topdeck key written first, coach overrides second -- the order that
    already worked before ``_write_topdeck_config`` was fixed to round-trip
    a nested sub-table, since it never touched ``[claude.coach]`` here."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)
    cli_module._write_topdeck_config(api_key="topdeck-key")
    _seed_coach_table(tmp_path)

    cfg = llm_config_module.load()
    assert cfg.api_key == "base-key"
    assert cfg.model == "claude-opus-5-5"
    assert cfg.effort == "high"

    coach = llm_config_module.load_coach()
    assert coach.model == "claude-fable-5-1"
    assert coach.effort == "max"
    assert coach.web_search is False

    from sensei_top.metagame import config as topdeck_config_module

    assert topdeck_config_module.load().api_key == "topdeck-key"

    # A later plain --set-effort write must not disturb the coach table or
    # the topdeck table -- they are separate tables, merged not replaced.
    cli_module._write_llm_config(api_key=None, model=None, effort="low")
    assert llm_config_module.load().effort == "low"
    coach_again = llm_config_module.load_coach()
    assert coach_again.model == "claude-fable-5-1"
    assert coach_again.effort == "max"
    assert coach_again.web_search is False
    assert topdeck_config_module.load().api_key == "topdeck-key"


def test_write_topdeck_config_after_coach_overrides_preserves_the_coach_table(
    monkeypatch, tmp_path
):
    """Coach overrides written first, topdeck key second: ``[claude.coach]``
    must survive as a table, not a stringified dict, because
    ``_write_topdeck_config`` reads and rewrites every table through
    ``_read_config_tables``/``_write_config_tables``. Those helpers must
    round-trip one level of nesting and real booleans for this order to be
    safe."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.metagame import config as topdeck_config_module

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)
    _seed_coach_table(tmp_path)
    cli_module._write_topdeck_config(api_key="topdeck-key")

    coach = llm_config_module.load_coach()
    assert coach.model == "claude-fable-5-1"
    assert coach.effort == "max"
    assert coach.web_search is False
    assert isinstance(coach.web_search, bool)

    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"


def test_write_mtgo_config_preserves_the_claude_and_topdeck_tables(monkeypatch, tmp_path):
    """This is the test that protects a real Anthropic API key: writing the
    MTGO handle must merge into config.toml, never replace it -- and the
    reverse order (mtgo written first, credentials after) must be just as
    safe, mirroring the two coach/topdeck ordering tests above."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.metagame import config as topdeck_config_module
    from sensei_top.mtgo.config import load_handle

    cli_module._write_llm_config(api_key="base-key", model="claude-sonnet-5", effort="low")
    cli_module._write_topdeck_config(api_key="topdeck-key")
    cli_module._write_mtgo_config(handle="Player1")

    cfg = llm_config_module.load()
    assert cfg.api_key == "base-key"
    assert cfg.model == "claude-sonnet-5"
    assert cfg.effort == "low"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "Player1"

    # Reverse order: writing the mtgo handle again after the fact must not
    # disturb either credential table.
    cli_module._write_mtgo_config(handle="otherhandle")
    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "otherhandle"


def test_write_backup_config_preserves_the_claude_topdeck_and_mtgo_tables(monkeypatch, tmp_path):
    """The fourth writer gets the same guarantee as the other three: writing
    backup settings must merge into config.toml, never replace it -- checked
    in both orders, mirroring the mtgo/topdeck ordering tests above."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.backup import config as backup_config_module
    from sensei_top.backup.config import BACKUP_DIR_ENV
    from sensei_top.metagame import config as topdeck_config_module
    from sensei_top.mtgo.config import load_handle

    monkeypatch.delenv(BACKUP_DIR_ENV, raising=False)

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)
    cli_module._write_topdeck_config(api_key="topdeck-key")
    cli_module._write_mtgo_config(handle="Player1")
    cli_module._write_backup_config(directory=str(tmp_path / "some-backups"), keep=3)

    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "Player1"
    backup_cfg = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert backup_cfg.directory == tmp_path / "some-backups"
    assert backup_cfg.keep == 3

    # Reverse order: writing backup settings first must not disturb a
    # credential table written afterwards, any more than the reverse did.
    cli_module._write_backup_config(directory=str(tmp_path / "other-backups"), keep=5)
    cli_module._write_mtgo_config(handle="otherhandle")
    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "otherhandle"
    backup_cfg_again = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert backup_cfg_again.directory == tmp_path / "other-backups"
    assert backup_cfg_again.keep == 5


def test_setting_mtgo_dir_alone_does_not_erase_a_configured_handle(monkeypatch, tmp_path):
    """Mirrors test_setting_backup_keep_alone_does_not_erase_a_configured_backup_dir
    just below for mtgo's own two-field table, now that _write_mtgo_config
    merges within its own table too: --set-mtgo-dir run on its own, on a
    later occasion than --set-mtgo-handle, must not blank the handle back to
    unconfigured -- and the reverse must hold too."""
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.mtgo.config import load_handle, resolve_log_dir

    cli_module._write_mtgo_config(handle="Player1")
    cli_module._write_mtgo_config(directory=str(tmp_path / "mtgo-share"))

    assert load_handle() == "Player1"
    directory, source = resolve_log_dir()
    assert directory == tmp_path / "mtgo-share"
    assert source == "config.toml [mtgo] dir"

    # And the reverse: setting the handle again afterwards must not erase
    # the directory set moments ago.
    cli_module._write_mtgo_config(handle="Player2")
    assert load_handle() == "Player2"
    directory_again, _ = resolve_log_dir()
    assert directory_again == tmp_path / "mtgo-share"


def test_setting_backup_keep_alone_does_not_erase_a_configured_backup_dir(monkeypatch, tmp_path):
    """Pins the field-level merge _write_backup_config's own docstring names
    as the likeliest bug in it: --set-backup-keep run on its own, on a later
    occasion than --set-backup-dir, must not blank the directory back to the
    default beside the database -- and the reverse must hold too."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.backup import config as backup_config_module
    from sensei_top.backup.config import BACKUP_DIR_ENV

    monkeypatch.delenv(BACKUP_DIR_ENV, raising=False)

    cli_module._write_backup_config(directory=str(tmp_path / "custom-backups"))
    cli_module._write_backup_config(keep=5)

    cfg = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert cfg.directory == tmp_path / "custom-backups"
    assert cfg.keep == 5

    # And the reverse: setting the directory again afterwards must not
    # erase the keep count set moments ago.
    cli_module._write_backup_config(directory=str(tmp_path / "another-dir"))
    cfg_again = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert cfg_again.directory == tmp_path / "another-dir"
    assert cfg_again.keep == 5


def test_config_shows_mtgo_not_configured_and_names_the_fix(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    parser = cli_module.build_parser()
    args = parser.parse_args(["config"])
    args.func(args)

    out = capsys.readouterr().out
    assert "No MTGO handle configured" in out
    assert "--set-mtgo-handle" in out


def test_config_shows_the_configured_mtgo_handle_in_full(monkeypatch, tmp_path, capsys):
    """The handle is the user's own account name, not a secret -- it must
    print in full, unlike the two API keys shown elsewhere in this output."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_mtgo_config(handle="Player1")

    parser = cli_module.build_parser()
    args = parser.parse_args(["config"])
    args.func(args)

    out = capsys.readouterr().out
    assert "MTGO handle source:" in out
    assert "Player1" in out


def test_config_set_mtgo_handle_flag_writes_and_preserves_claude_key(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)

    from sensei_top.mtgo.config import load_handle

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-handle", "Player1"])
    args.func(args)

    assert load_handle() == "Player1"
    assert llm_config_module.load().api_key == "base-key"


# --- mtgo/config.py: resolve_log_dir() -------------------------------------


def test_resolve_log_dir_env_wins_over_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(directory=str(tmp_path / "from-config"))
    env_dir = tmp_path / "from-env"
    monkeypatch.setenv("MTGO_LOG_DIR", str(env_dir))

    directory, source = resolve_log_dir()
    assert directory == env_dir
    assert source == "$MTGO_LOG_DIR"


def test_resolve_log_dir_reads_the_config_file_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(directory=str(tmp_path / "from-config"))

    directory, source = resolve_log_dir()
    assert directory == tmp_path / "from-config"
    assert source == "config.toml [mtgo] dir"


def test_resolve_log_dir_expands_a_tilde_in_the_env_var(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # expanduser on Windows
    monkeypatch.setenv("MTGO_LOG_DIR", "~/mtgo-share")
    from sensei_top.mtgo.config import resolve_log_dir

    directory, source = resolve_log_dir()
    assert directory == fake_home / "mtgo-share"
    assert source == "$MTGO_LOG_DIR"


def test_resolve_log_dir_empty_env_falls_through_to_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MTGO_LOG_DIR", "")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(directory=str(tmp_path / "from-config"))

    directory, source = resolve_log_dir()
    assert directory == tmp_path / "from-config"
    assert source == "config.toml [mtgo] dir"


def test_resolve_log_dir_is_none_and_silent_with_no_config_file(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert caplog.messages == []


def test_resolve_log_dir_is_none_and_silent_with_a_handle_only_table(monkeypatch, tmp_path, caplog):
    """An install that configured an MTGO handle but never a directory (the
    common case -- plenty of installs stay Arena-only) must resolve
    silently, not warn -- unlike a config file that's actually broken."""
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(handle="Player1")

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert caplog.messages == []


def test_resolve_log_dir_warns_on_an_empty_dir_value(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[mtgo]\ndir = ""\n')

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert any("not a usable path" in message for message in caplog.messages)


def test_resolve_log_dir_warns_on_a_non_string_dir_value(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("[mtgo]\ndir = 42\n")

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert any("not a usable path" in message for message in caplog.messages)


def test_resolve_log_dir_warns_on_unreadable_toml(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not { valid toml at all")

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert any("could not read" in message for message in caplog.messages)


# --- cli.py: the config subcommand's --set-mtgo-dir flag -------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no mode 600; the test below")
def test_config_set_mtgo_dir_flag_writes_the_resolved_path(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.mtgo.config import resolve_log_dir

    share = tmp_path / "mtgo-share"
    share.mkdir()

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-dir", str(share)])
    args.func(args)

    out = capsys.readouterr().out
    assert f"MTGO log directory written to {config_module.config_path()} (mode 600)." in out

    directory, source = resolve_log_dir()
    assert directory == share.resolve()
    assert source == "config.toml [mtgo] dir"


def test_config_set_mtgo_dir_flag_omits_mode_600_on_windows(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")

    share = tmp_path / "mtgo-share"
    share.mkdir()

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-dir", str(share)])
    args.func(args)

    out = capsys.readouterr().out
    assert f"MTGO log directory written to {config_module.config_path()}." in out
    assert "(mode 600)" not in out


def test_config_set_mtgo_dir_flag_on_a_directory_that_does_not_exist_yet(
    monkeypatch, tmp_path, capsys
):
    """A share mounted later is the normal case (cmd_config's --set-mtgo-dir
    branch) -- the value is still stored, with a note rather than a
    refusal."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.mtgo.config import resolve_log_dir

    not_yet_mounted = tmp_path / "not-mounted-yet"

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-dir", str(not_yet_mounted)])
    args.func(args)

    out = capsys.readouterr().out
    assert "does not exist yet; stored anyway" in out
    assert "MTGO log directory written to" in out

    directory, _source = resolve_log_dir()
    assert directory == not_yet_mounted.resolve()


def test_config_status_names_the_mtgo_directory_and_its_source(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_mtgo_config(directory=str(tmp_path / "mtgo-share"))

    parser = cli_module.build_parser()
    args = parser.parse_args(["config"])
    args.func(args)

    out = capsys.readouterr().out
    assert "MTGO directory source: config.toml" in out
    assert str(tmp_path / "mtgo-share") in out


# --- config_path() on Windows ------------------------------------------------
# These monkeypatch sys.platform and the environment into tmp_path trees, so
# on real Windows they exercise the same branch; none needs to skip there.


def _windows_env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    home.mkdir()
    appdata.mkdir()
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(config_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(config_module, "_warned_old_config", False)
    return home / ".config" / "sensei-top" / "config.toml", appdata / "sensei-top" / "config.toml"


def test_windows_config_lives_in_appdata(monkeypatch, tmp_path):
    _old, new = _windows_env(monkeypatch, tmp_path)
    assert config_module.config_path() == new


def test_windows_falls_back_to_the_old_file_and_warns_once(monkeypatch, tmp_path, caplog):
    old, new = _windows_env(monkeypatch, tmp_path)
    old.parent.mkdir(parents=True)
    old.write_text('[claude]\napi_key = "old-key"\n')
    with caplog.at_level("WARNING", logger=config_module.log.name):
        assert config_module.config_path() == old
        assert load() == LLMConfig(api_key="old-key")
    warnings = [r.getMessage() for r in caplog.records if "now belongs at" in r.getMessage()]
    assert warnings == [
        f"config file read from {old}; on Windows it now belongs at {new}, so move it there"
    ]
    assert not new.exists()


def test_windows_new_file_wins_over_the_old_one(monkeypatch, tmp_path, caplog):
    old, new = _windows_env(monkeypatch, tmp_path)
    for path in (old, new):
        path.parent.mkdir(parents=True)
    old.write_text('[claude]\napi_key = "old-key"\n')
    new.write_text('[claude]\napi_key = "new-key"\n')
    assert config_module.config_path() == new
    assert load().api_key == "new-key"
    assert not [r for r in caplog.records if "now belongs at" in r.getMessage()]


def test_xdg_config_home_wins_on_windows_too(monkeypatch, tmp_path):
    _windows_env(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_module.config_path() == tmp_path / "xdg" / "sensei-top" / "config.toml"


def test_non_windows_keeps_dot_config_even_with_appdata_set(monkeypatch, tmp_path):
    old, _new = _windows_env(monkeypatch, tmp_path)
    monkeypatch.setattr(config_module.sys, "platform", "linux")
    assert config_module.config_path() == old


# --- key_source(): which of the three places the key in force came from -----


def test_llm_key_source_follows_the_resolution_order(monkeypatch, memory_keyring):
    assert llm_config_module.key_source() is None
    cli_module._write_llm_config(api_key="file-key", model=None, effort=None)
    assert llm_config_module.key_source() == "file"
    memory_keyring[("sensei-top", "claude")] = "keyring-key"
    assert llm_config_module.key_source() == "keyring"
    assert llm_config_module.load().api_key == "keyring-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert llm_config_module.key_source() == "env"
    assert llm_config_module.load().api_key == "env-key"


def test_topdeck_key_source_follows_the_resolution_order(monkeypatch, memory_keyring):
    from sensei_top.metagame import config as topdeck_config

    assert topdeck_config.key_source() is None
    cli_module._write_topdeck_config(api_key="file-key")
    assert topdeck_config.key_source() == "file"
    memory_keyring[("sensei-top", "topdeck")] = "keyring-key"
    assert topdeck_config.key_source() == "keyring"
    assert topdeck_config.load().api_key == "keyring-key"
    monkeypatch.setenv("TOPDECK_API_KEY", "env-key")
    assert topdeck_config.key_source() == "env"


def test_a_model_can_be_set_before_any_key(memory_keyring):
    """The key may live in the keyring, so the file's [claude] table can hold
    a model with no api_key beside it."""
    cli_module._write_llm_config(api_key=None, model="claude-sonnet-5", effort="low")
    assert llm_config_module.load() is None
    memory_keyring[("sensei-top", "claude")] = "keyring-key"
    cfg = llm_config_module.load()
    assert (cfg.api_key, cfg.model, cfg.effort) == ("keyring-key", "claude-sonnet-5", "low")
