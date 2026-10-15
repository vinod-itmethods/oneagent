"""One-time catch-up on first start, so the first brief already knows about the last few days.

After this, the bot keeps itself up to date from live Slack events.
"""

import logging
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from slack_sdk.errors import SlackApiError

from .config import Config
from .slack_reader import SlackReader, hours_ago
from .store import Store
from .tracker import Tracker

log = logging.getLogger(__name__)


def backfill(config: Config, store: Store, reader: SlackReader, tracker: Tracker, skip_channel: str) -> None:
    if store.get("backfill_done") or config.backfill_days <= 0:
        return
    since = hours_ago(config.backfill_days * 24)
    events: dict[tuple[str, str], dict] = {}

    def add(msg: dict, channel: str, channel_type: str) -> None:
        if float(msg["ts"]) >= since:
            events[(channel, msg["ts"])] = {**msg, "channel": channel, "channel_type": channel_type}

    def add_thread(channel: str, thread_ts: str, channel_type: str) -> None:
        try:
            for reply in reader.replies(channel, thread_ts):
                add(reply, channel, channel_type)
        except SlackApiError as e:
            log.warning("backfill: replies %s/%s failed: %s", channel, thread_ts, e)

    # 1. DMs and group DMs
    for convo in reader.my_dms():
        if convo["id"] == skip_channel or convo.get("user") == "USLACKBOT":
            continue
        channel_type = "im" if convo.get("is_im") else "mpim"
        try:
            for msg in reader.history(convo["id"], oldest=since, limit=100):
                add(msg, convo["id"], channel_type)
                if msg.get("reply_count"):
                    add_thread(convo["id"], msg["ts"], channel_type)
        except SlackApiError as e:
            log.warning("backfill: history %s failed: %s", convo["id"], e)

    # 2. @mentions in channels (with their threads, so your replies are seen)
    after = (datetime.fromtimestamp(since) - timedelta(days=1)).strftime("%Y-%m-%d")
    for match in reader.search(f"<@{config.owner_user_id}> after:{after}", count=100):
        channel = match.get("channel", {})
        if channel.get("is_im") or channel.get("is_mpim"):
            continue  # already covered above
        thread_ts = parse_qs(urlparse(match.get("permalink", "")).query).get("thread_ts", [None])[0]
        add_thread(channel["id"], thread_ts or match["ts"], "channel")

    for event in sorted(events.values(), key=lambda e: float(e["ts"])):
        tracker.on_message(event)

    store.put("backfill_done", True)
    log.info("backfill: processed %d messages from the last %d days", len(events), config.backfill_days)
