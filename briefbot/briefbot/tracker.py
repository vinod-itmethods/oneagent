"""Decides which incoming messages are addressed to you, and when you've answered them.

Addressed to you:
  * any message in a 1:1 DM or group DM
  * an @mention of you (or of one of your user groups) anywhere
  * a reply in a thread you started or posted in

Answered when:
  * you reply in the same thread, or
  * you post in the same DM / group DM after it, or
  * you post top-level in a channel and @mention the person who asked, or
  * you react to it with any emoji (configurable), or
  * you press "Mark handled" in the brief.
"""

import re
from typing import Optional

from .config import Config
from .store import Store

# Message subtypes that are real messages from a person. Everything else
# (joins, topic changes, edits, ...) is ignored.
TRACKED_SUBTYPES = {None, "thread_broadcast", "file_share", "me_message"}


class Tracker:
    def __init__(self, store: Store, config: Config):
        self.store = store
        self.config = config
        self.owner = config.owner_user_id
        self._mention_patterns = [f"<@{self.owner}>"] + [
            f"<!subteam^{gid}" for gid in config.owner_usergroup_ids
        ]

    def on_message(self, event: dict) -> Optional[str]:
        """Process one Slack `message` event. Returns the action taken (for logs/tests)."""
        subtype = event.get("subtype")
        channel = event.get("channel")

        if subtype == "message_deleted":
            deleted_ts = (event.get("previous_message") or {}).get("ts") or event.get("deleted_ts")
            if deleted_ts and self.store.resolve_one(channel, deleted_ts, "deleted"):
                return "deleted"
            return None
        if subtype not in TRACKED_SUBTYPES:
            return None

        user = event.get("user")
        ts = event["ts"]
        thread_ts = event.get("thread_ts")
        if thread_ts == ts:  # a thread parent is a top-level message
            thread_ts = None
        text = event.get("text") or ""

        if user == self.owner:
            return self._on_my_message(channel, event.get("channel_type"), ts, thread_ts, text)

        if event.get("bot_id") and not self.config.include_bot_messages:
            return None
        if not user and not event.get("bot_id"):
            return None

        kind = self._classify(event, channel, thread_ts, text)
        if not kind:
            return None
        self.store.add_pending(channel, ts, thread_ts, user, text, kind)
        return f"pending:{kind}"

    def on_reaction(self, event: dict) -> Optional[str]:
        if not self.config.reaction_counts_as_reply or event.get("user") != self.owner:
            return None
        item = event.get("item") or {}
        if item.get("type") != "message":
            return None
        if self.store.resolve_one(item["channel"], item["ts"], "reaction"):
            return "resolved:reaction"
        return None

    # -------------------------------------------------------------------------

    def _classify(self, event: dict, channel: str, thread_ts: Optional[str], text: str) -> Optional[str]:
        channel_type = event.get("channel_type")
        if channel_type == "im":
            return "dm"
        if channel_type == "mpim":
            return "group_dm"
        if any(p in text for p in self._mention_patterns):
            return "mention"
        if thread_ts and self.store.is_my_thread(channel, thread_ts):
            return "thread_reply"
        return None

    def _on_my_message(
        self, channel: str, channel_type: Optional[str], ts: str, thread_ts: Optional[str], text: str
    ) -> str:
        if thread_ts:
            self.store.remember_thread(channel, thread_ts)
            self.store.resolve_thread(channel, thread_ts, before_ts=ts)
            return "resolved:thread"

        # Top-level message: it may become a thread parent, so remember it.
        self.store.remember_thread(channel, ts)
        if channel_type in ("im", "mpim"):
            # In a DM, any reply from you answers everything before it.
            self.store.resolve_top_level(channel, before_ts=ts)
        else:
            # In a busy channel, only count it as a reply if you @mention the asker.
            mentioned = re.findall(r"<@([A-Z0-9]+)>", text)
            self.store.resolve_top_level(channel, before_ts=ts, from_users=mentioned)
        return "resolved:top_level"

