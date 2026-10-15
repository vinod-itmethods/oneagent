"""Settings, loaded once from environment variables (or a .env file)."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    # Slack credentials
    bot_token: str = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token: str = os.environ.get("SLACK_APP_TOKEN", "")
    user_token: str = os.environ.get("SLACK_USER_TOKEN", "")

    # The one person this bot works for. Everyone else is ignored.
    owner_user_id: str = os.environ.get("OWNER_USER_ID", "")
    # User groups you belong to (e.g. S0123ABC); @mentions of them count as addressed to you.
    owner_usergroup_ids: list[str] = field(default_factory=lambda: _list("OWNER_USERGROUP_IDS"))

    # Claude
    claude_provider: str = os.getenv("CLAUDE_PROVIDER", "anthropic")  # "anthropic" or "bedrock"
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")

    # Morning brief schedule
    timezone: str = os.getenv("TIMEZONE", "America/Toronto")
    brief_time: str = os.getenv("BRIEF_TIME", "08:30")
    brief_days: str = os.getenv("BRIEF_DAYS", "mon-fri")
    highlight_channels: list[str] = field(default_factory=lambda: _list("HIGHLIGHT_CHANNELS"))

    # Tracking behaviour
    max_age_days: int = int(os.getenv("MAX_AGE_DAYS", "14"))
    backfill_days: int = int(os.getenv("BACKFILL_DAYS", "3"))
    reaction_counts_as_reply: bool = _bool("REACTION_COUNTS_AS_REPLY", True)
    include_bot_messages: bool = _bool("INCLUDE_BOT_MESSAGES", False)

    db_path: str = os.getenv("DB_PATH", "briefbot.db")

    def validate(self) -> None:
        missing = [
            name
            for name, value in [
                ("SLACK_BOT_TOKEN", self.bot_token),
                ("SLACK_APP_TOKEN", self.app_token),
                ("SLACK_USER_TOKEN", self.user_token),
                ("OWNER_USER_ID", self.owner_user_id),
            ]
            if not value
        ]
        if missing:
            raise SystemExit(f"Missing required settings: {', '.join(missing)} (see .env.example)")
