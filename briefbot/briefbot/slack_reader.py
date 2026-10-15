"""Read-only access to your Slack, using your *user* token.

The user token sees exactly what you see: your DMs, group DMs, private channels
and public channels, plus Slack search. The bot never posts with it.
"""

import logging
import time
from datetime import datetime
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

log = logging.getLogger(__name__)

MAX_TEXT = 1500


class SlackReader:
    def __init__(self, user_token: str, timezone: str):
        self.client = WebClient(token=user_token)
        self.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
        self.tz = ZoneInfo(timezone)
        self._channels_by_name: dict[str, str] = {}

    # --- names ---------------------------------------------------------------

    @lru_cache(maxsize=2048)
    def user_name(self, user_id: Optional[str]) -> str:
        if not user_id:
            return "someone"
        try:
            user = self.client.users_info(user=user_id)["user"]
            profile = user.get("profile", {})
            return profile.get("display_name") or profile.get("real_name") or user.get("name") or user_id
        except SlackApiError:
            return user_id

    @lru_cache(maxsize=2048)
    def channel_label(self, channel_id: str) -> str:
        """'#general', 'DM with Alice', or 'group DM (Alice, Bob)'."""
        try:
            ch = self.client.conversations_info(channel=channel_id)["channel"]
        except SlackApiError:
            return channel_id
        if ch.get("is_im"):
            return f"DM with {self.user_name(ch.get('user'))}"
        if ch.get("is_mpim"):
            try:
                members = self.client.conversations_members(channel=channel_id)["members"]
                return "group DM (" + ", ".join(self.user_name(m) for m in members[:6]) + ")"
            except SlackApiError:
                return "group DM"
        return f"#{ch.get('name', channel_id)}"

    def permalink(self, channel: str, ts: str) -> Optional[str]:
        try:
            return self.client.chat_getPermalink(channel=channel, message_ts=ts)["permalink"]
        except SlackApiError:
            return None

    def resolve_channel(self, name_or_id: str) -> Optional[str]:
        """Turn '#eng', 'eng' or 'C0123' into a channel ID (only channels you're in)."""
        value = name_or_id.strip().lstrip("#")
        if value[:1] in ("C", "G", "D") and value.isupper() and len(value) >= 9:
            return value
        if not self._channels_by_name:
            cursor = None
            while True:
                resp = self.client.users_conversations(
                    types="public_channel,private_channel", exclude_archived=True, limit=999, cursor=cursor
                )
                for ch in resp["channels"]:
                    self._channels_by_name[ch["name"]] = ch["id"]
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        return self._channels_by_name.get(value.lower())

    # --- reading -------------------------------------------------------------

    def search(self, query: str, count: int = 20) -> list[dict]:
        resp = self.client.search_messages(query=query, count=min(count, 100), sort="timestamp")
        return resp.get("messages", {}).get("matches", [])

    def history(self, channel: str, oldest: float, limit: int = 200) -> list[dict]:
        messages, cursor = [], None
        while len(messages) < limit:
            resp = self.client.conversations_history(
                channel=channel, oldest=str(oldest), limit=min(200, limit), cursor=cursor
            )
            messages.extend(resp["messages"])
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not resp.get("has_more") or not cursor:
                break
        return sorted(messages, key=lambda m: float(m["ts"]))

    def replies(self, channel: str, thread_ts: str) -> list[dict]:
        return self.client.conversations_replies(channel=channel, ts=thread_ts, limit=200)["messages"]

    def my_dms(self) -> list[dict]:
        convos, cursor = [], None
        while True:
            resp = self.client.users_conversations(types="im,mpim", limit=999, cursor=cursor)
            convos.extend(resp["channels"])
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                return convos

    # --- formatting ----------------------------------------------------------

    def when(self, ts: str) -> str:
        return datetime.fromtimestamp(float(ts), self.tz).strftime("%a %b %d %H:%M")

    def format_message(self, msg: dict, channel: Optional[str] = None) -> str:
        """One line per message, readable by both Claude and humans."""
        channel_id = channel or (msg.get("channel") or {}).get("id") or ""
        where = self.channel_label(channel_id) if channel_id else "?"
        who = self.user_name(msg.get("user")) if msg.get("user") else msg.get("username", "bot")
        text = (msg.get("text") or "").replace("\n", " ")
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "…"
        refs = f"channel={channel_id} ts={msg['ts']}"
        if msg.get("thread_ts") and msg["thread_ts"] != msg["ts"]:
            refs += f" thread_ts={msg['thread_ts']}"
        if msg.get("reply_count"):
            refs += f" replies={msg['reply_count']}"
        if msg.get("permalink"):
            refs += f" {msg['permalink']}"
        return f"[{self.when(msg['ts'])}] {where} | {who}: {text} ({refs})"


def hours_ago(hours: float) -> float:
    return time.time() - hours * 3600
