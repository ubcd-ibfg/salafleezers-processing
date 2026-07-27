"""Tests for the `sfz gui` CLI command's security-posture surfacing."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from salafleezers.cli.main import _print_security_posture, app

runner = CliRunner()


class TestSecurityPostureTable:
    def test_renders_default_local_posture(self, capsys):
        _print_security_posture(data_root=None, allow_origin=None, rate_limit=None)
        out = capsys.readouterr().out
        assert "disabled (local-only)" in out
        assert "unrestricted" in out
        assert "built-in localhost defaults" in out
        assert "disabled" in out   # rate limit

    def test_renders_hardened_posture_without_leaking_token(self, capsys, monkeypatch):
        monkeypatch.setenv("SFZ_AUTH_TOKEN", "super-secret-value")
        _print_security_posture(
            data_root=Path("/data/traces"),
            allow_origin=["https://lab.example.com"],
            rate_limit=120,
        )
        out = capsys.readouterr().out
        assert "shared-secret bearer token" in out
        assert "/data/traces" in out
        assert "https://lab.example.com" in out
        assert "120 req/min" in out
        assert "super-secret-value" not in out   # never print the token itself


class TestGuiCommandWiring:
    def test_data_root_and_rate_limit_set_env_vars(self, monkeypatch):
        # The CLI mutates os.environ directly (not via monkeypatch), so
        # monkeypatch can't auto-revert it -- clean up manually or these
        # leak into every later test in the same pytest process.
        monkeypatch.delenv("SFZ_DATA_ROOT", raising=False)
        monkeypatch.delenv("SFZ_RATE_LIMIT_PER_MINUTE", raising=False)
        try:
            fake_app = MagicMock()
            with (
                patch(
                    "salafleezers.web.app.create_app", return_value=fake_app
                ) as mock_create,
                patch("uvicorn.run") as mock_run,
            ):
                result = runner.invoke(app, [
                    "gui", "--no-browser",
                    "--data-root", "/tmp/some-data-root",
                    "--rate-limit", "42",
                ])

            assert result.exit_code == 0, result.output
            assert os.environ["SFZ_DATA_ROOT"] == "/tmp/some-data-root"
            assert os.environ["SFZ_RATE_LIMIT_PER_MINUTE"] == "42"
            mock_create.assert_called_once()
            mock_run.assert_called_once()
        finally:
            os.environ.pop("SFZ_DATA_ROOT", None)
            os.environ.pop("SFZ_RATE_LIMIT_PER_MINUTE", None)

    def test_allow_origin_passed_through_to_create_app(self, monkeypatch):
        monkeypatch.delenv("SFZ_DATA_ROOT", raising=False)
        monkeypatch.delenv("SFZ_RATE_LIMIT_PER_MINUTE", raising=False)

        fake_app = MagicMock()
        with (
            patch(
                "salafleezers.web.app.create_app", return_value=fake_app
            ) as mock_create,
            patch("uvicorn.run"),
        ):
            result = runner.invoke(app, [
                "gui", "--no-browser",
                "--allow-origin", "https://a.example.com",
                "--allow-origin", "https://b.example.com",
            ])

        assert result.exit_code == 0, result.output
        mock_create.assert_called_once_with(
            allow_origins=["https://a.example.com", "https://b.example.com"]
        )
