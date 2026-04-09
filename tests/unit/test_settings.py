"""Tests for settings loading and validation."""

from pathlib import Path

import pytest
import yaml


def write_config(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(data))
    return p


class TestSettings:
    def test_load_minimal_valid_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from jobagent.settings import load_settings

        # Clear env-var override that CI sets (ANTHROPIC_API_KEY=sk-ant-test-dummy)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        cfg_path = write_config(tmp_path, {"anthropic": {"api_key": "sk-ant-test"}})
        settings = load_settings(cfg_path)
        assert settings.anthropic.api_key.get_secret_value() == "sk-ant-test"

    def test_env_var_overrides_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from jobagent.settings import load_settings

        cfg_path = write_config(tmp_path, {"anthropic": {"api_key": "sk-ant-original"}})
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
        settings = load_settings(cfg_path)
        assert settings.anthropic.api_key.get_secret_value() == "sk-ant-from-env"

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        from jobagent.settings import load_settings

        with pytest.raises(FileNotFoundError):
            load_settings(tmp_path / "nonexistent.yaml")

    def test_default_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from jobagent.settings import load_settings

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg_path = write_config(tmp_path, {"anthropic": {"api_key": "sk-ant-test"}})
        settings = load_settings(cfg_path)
        assert settings.search.min_match_score == 70
        assert settings.application.max_applications_per_day == 10
        assert settings.whatsapp.provider == "mock"

    def test_score_threshold_validation(self) -> None:
        from pydantic import ValidationError

        from jobagent.settings import SearchSettings

        with pytest.raises(ValidationError):
            SearchSettings(min_match_score=150)
