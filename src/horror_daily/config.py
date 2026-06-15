from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "DSV4Pro"
    itad_api_key: str = ""
    itad_country: str = "CN"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = False
    smtp_use_tls: bool = True
    mail_from: str = ""
    mail_to: str = ""

    tz: str = "Asia/Singapore"
    database_path: Path = Path("data/horror_daily.sqlite3")
    report_dir: Path = Path("reports")
    log_level: str = "INFO"

    config_path: Path = Field(default=Path("config/settings.yaml"))

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(override=True)
    return Settings()


@lru_cache(maxsize=1)
def load_yaml_config(path: str | Path | None = None) -> dict[str, Any]:
    settings = get_settings()
    config_path = Path(path or settings.config_path)
    with config_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
