"""Runtime settings, sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    vision_model: str
    max_upload_mb: int
    batch_concurrency: int
    app_name: str
    environment: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            vision_model=os.getenv("VISION_MODEL", "claude-sonnet-4-5"),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
            batch_concurrency=int(os.getenv("BATCH_CONCURRENCY", "4")),
            app_name=os.getenv("APP_NAME", "TTB Label Review"),
            environment=os.getenv("ENVIRONMENT", "prototype"),
        )


settings = Settings.from_env()
