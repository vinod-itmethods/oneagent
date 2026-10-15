"""Builds the morning brief: a Claude summary on top, then every unanswered item with a link."""

import logging
import time

from .assistant import Assistant
from .config import Config
from .slack_reader import SlackReader, hours_ago
from .store import Pending, Store

log = logging.getLogger(__name__)

MAX_ITEM_BLOCKS = 20  # Slack allows 50 blocks per message; leave room for the header and summary.
KIND_LABEL = {"dm": "DM", "group_dm": "Group DM", "mention": "@mention", "thread_reply": "Thread reply"}


def age(hours: float) -> str:
    if hours < 1:
        return f"{max(1, int(hours * 60))}m ago"
    if hours < 48:
        return f"{int(hours)}h ago"
    return f"{int(hours // 24)}d ago"


class BriefBuilder:
    def __init__(self, config: Config, store: Store, reader: SlackReader, assistant: Assistant):
        self.config = config
        self.store = store
        self.reader = reader
        self.assistant = assistant

    def build(self) -> tuple[str, list[dict]]:
        """Returns (fallback_text, blocks)."""
        items = self.store.open_items(self.config.max_age_days)
        # Channel highlights cover everything since the last brief (at most 3 days, so Monday covers the weekend).
        since = max(self.store.get("last_brief_at") or hours_ago(24), hours_ago(72))
        highlights = self._channel_highlights(since)
        self.store.put("last_brief_at", time.time())

        if not items and not highlights:
            return "Nothing waiting on you.", [_section(":white_check_mark: *You're all caught up.* Nothing is waiting on your reply.")]

        items_text = "\n".join(self._describe(p) for p in items)
        try:
            summary = self.assistant.summarize_brief(items_text, highlights)
        except Exception:
            log.exception("summary failed; sending the list without it")
            summary = ""

        blocks: list[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": ":sunrise: Your Slack brief"}},
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"*{len(items)}* message(s) waiting on your reply"}],
            },
        ]
        if summary:
            blocks.append(_section(summary[:2900]))
        if items:
            blocks.append({"type": "divider"})
            numbered = list(enumerate(reversed(items), start=1))  # newest first
            for n, p in numbered[:MAX_ITEM_BLOCKS]:
                blocks.append(self._item_block(n, p))
            if len(items) > MAX_ITEM_BLOCKS:
                blocks.append(
                    {"type": "context", "elements": [{"type": "mrkdwn", "text": f"…and {len(items) - MAX_ITEM_BLOCKS} older. Ask me _\"what else is waiting on me?\"_"}]}
                )
            self.store.put("last_brief", {str(n): p.id for n, p in numbered})
            blocks.append(
                {"type": "context", "elements": [{"type": "mrkdwn", "text": "Reply, react, or press *Handled* to clear an item. `done 2 5` clears several at once."}]}
            )
        return f"Your Slack brief: {len(items)} message(s) waiting on your reply", blocks

    # -------------------------------------------------------------------------

    def _describe(self, p: Pending) -> str:
        return (
            f"- [{KIND_LABEL[p.kind]}] {self.reader.user_name(p.user)} in {self.reader.channel_label(p.channel)}, "
            f"{age(p.age_hours)}: {p.text[:400]}"
        )

    def _item_block(self, n: int, p: Pending) -> dict:
        link = self.reader.permalink(p.channel, p.ts)
        snippet = " ".join(p.text.split())[:220] + ("…" if len(p.text) > 220 else "")
        where = self.reader.channel_label(p.channel)
        where = f"<{link}|{where}>" if link else where
        return {
            "type": "section",
            "block_id": f"item_{p.id}",
            "text": {
                "type": "mrkdwn",
                "text": f"*{n}.* *{self.reader.user_name(p.user)}* · {where} · {KIND_LABEL[p.kind]} · _{age(p.age_hours)}_\n>{snippet}",
            },
            "accessory": {
                "type": "button",
                "action_id": "mark_handled",
                "value": str(p.id),
                "text": {"type": "plain_text", "text": "Handled"},
            },
        }

    def _channel_highlights(self, since: float) -> str:
        lines = []
        for name in self.config.highlight_channels:
            channel_id = self.reader.resolve_channel(name)
            if not channel_id:
                log.warning("highlight channel %s not found", name)
                continue
            for m in self.reader.history(channel_id, oldest=since, limit=150):
                if m.get("subtype") in (None, "thread_broadcast", "bot_message"):
                    lines.append(self.reader.format_message(m, channel_id))
        return "\n".join(lines)


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}
