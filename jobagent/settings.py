"""
JobAgent - Settings
Validated configuration using pydantic-settings.
Reads from environment variables and/or config.yaml.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AnthropicSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_key: SecretStr = Field(..., description="Anthropic API key")
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    max_retries: int = 3


class LinkedInSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    email: str = ""
    password: SecretStr = SecretStr("")
    use_cookies: bool = True
    cookies_file: Path = Path("config/linkedin_cookies.json")
    headless: bool = True
    slow_mo_ms: int = 50  # Human-like delay between actions


class SearchSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["Remote"])
    experience_levels: list[str] = Field(
        default_factory=lambda: ["Mid-Senior level", "Director"]
    )
    job_types: list[str] = Field(default_factory=lambda: ["Full-time"])
    date_posted: Literal["past_24h", "past_week", "past_month", "any"] = "past_week"
    easy_apply_only: bool = False
    max_jobs_per_scan: int = 50
    min_match_score: int = Field(70, ge=0, le=100)

    @field_validator("min_match_score")
    @classmethod
    def validate_score(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("min_match_score must be between 0 and 100")
        return v


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    auto_apply: bool = True
    require_whatsapp_approval: bool = True
    cover_letter: bool = True
    apply_delay_seconds: int = Field(30, ge=5)
    max_applications_per_day: int = Field(10, ge=1, le=50)


class TwilioSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    account_sid: str = ""
    auth_token: SecretStr = SecretStr("")
    from_number: str = ""
    to_number: str = ""


class WhatsAppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    provider: Literal["twilio", "callmebot", "mock"] = "mock"
    twilio: TwilioSettings = Field(default_factory=TwilioSettings)
    approval_timeout_minutes: int = Field(60, ge=1, le=1440)
    webhook_port: int = 8081


class CVSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    base_template: Path = Path("config/cv_template.html")
    output_dir: Path = Path("output/cvs")


class DashboardSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8080
    auto_open_browser: bool = True
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    path: Path = Path("data/jobs.db")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    anthropic: AnthropicSettings
    linkedin: LinkedInSettings = Field(default_factory=LinkedInSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    application: ApplicationSettings = Field(default_factory=ApplicationSettings)
    whatsapp: WhatsAppSettings = Field(default_factory=WhatsAppSettings)
    cv: CVSettings = Field(default_factory=CVSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)


def load_settings(config_path: str | Path = "config/config.yaml") -> Settings:
    """
    Load settings from YAML file, then override with environment variables.
    Environment variables take precedence (useful for secrets in CI/prod).
    """
    config_path = Path(config_path)

    if not config_path.exists():
        example = config_path.with_suffix(".example.yaml")
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Copy the example: cp {example} {config_path}"
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    # Allow env var override for secrets
    if api_key := os.getenv("ANTHROPIC_API_KEY"):
        raw.setdefault("anthropic", {})["api_key"] = api_key
    if twilio_sid := os.getenv("TWILIO_ACCOUNT_SID"):
        raw.setdefault("whatsapp", {}).setdefault("twilio", {})["account_sid"] = twilio_sid

    return Settings(**raw)
