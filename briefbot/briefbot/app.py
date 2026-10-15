"""Slack wiring: events in, answers and briefs out. Runs over Socket Mode, so no public URL is needed."""

import dataclasses
import logging
import re
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

from .assistant import Assistant
from .backfill import backfill
from .brief import BriefBuilder
from .config import Config
from .slack_reader import SlackReader
from .store import Store
from .tracker import Tracker

log = logging.getLogger("briefbot")

BRIEF_RE = re.compile(r"^\s*(brief|update|morning( update| brief)?|catch me up|what did i miss)\W*$", re.I)
DONE_RE = re.compile(r"^\s*done\s+([\d,\s]+)$", re.I)
HELP_RE = re.compile(r"^\s*(help|\?)\s*$", re.I)

HELP_TEXT = """*Here's what I can do*
• `brief` (or _"catch me up"_) — everything waiting on your reply, plus a summary of what matters most
• `done 2 5` — clear items 2 and 5 from the last brief
• Ask anything about your Slack, e.g.
   _"What did Priya ask me about the Q4 budget?"_
   _"Summarize #eng-incidents since Monday"_
   _"Any decisions on the SSO migration this week?"_
Follow-up questions in the same thread keep the context.
I also send the brief automatically every {days} at {time} ({tz})."""


def build_app(config: Config) -> tuple[App, callable]:
    app = App(token=config.bot_token)
    bot: WebClient = app.client

    # Who is the owner? The user token says, so the bot can't be pointed at someone else's data.
    token_owner = WebClient(token=config.user_token).auth_test()["user_id"]
    if config.owner_user_id and config.owner_user_id != token_owner:
        raise SystemExit(f"OWNER_USER_ID {config.owner_user_id} does not match the user token's owner {token_owner}")
    config = dataclasses.replace(config, owner_user_id=token_owner)
    owner = config.owner_user_id

    store = Store(config.db_path)
    reader = SlackReader(config.user_token, config.timezone)
    tracker = Tracker(store, config)
    assistant = Assistant(config, reader, store)
    briefs = BriefBuilder(config, store, reader, assistant)
    owner_dm = bot.conversations_open(users=owner)["channel"]["id"]

    def send_brief(thread_ts: str | None = None) -> None:
        text, blocks = briefs.build()
        bot.chat_postMessage(channel=owner_dm, text=text, blocks=blocks, thread_ts=thread_ts)

    def thread_history(thread_ts: str, current_ts: str) -> list[dict]:
        """Earlier turns of this conversation with the bot, as Claude messages."""
        msgs = bot.conversations_replies(channel=owner_dm, ts=thread_ts, limit=40)["messages"]
        history = []
        for m in msgs:
            if m["ts"] == current_ts or not m.get("text") or m.get("text", "").startswith("_Looking"):
                continue
            role = "user" if m.get("user") == owner else "assistant"
            history.append({"role": role, "content": m["text"]})
        while history and history[0]["role"] != "user":
            history.pop(0)
        return history

    def handle_owner_dm(event: dict) -> None:
        text = (event.get("text") or "").strip()
        reply_ts = event.get("thread_ts") or event["ts"]

        if HELP_RE.match(text) or not text:
            bot.chat_postMessage(
                channel=owner_dm,
                thread_ts=reply_ts,
                text=HELP_TEXT.format(days=config.brief_days, time=config.brief_time, tz=config.timezone),
            )
            return
        if BRIEF_RE.match(text):
            send_brief()
            return
        if m := DONE_RE.match(text):
            numbers = re.findall(r"\d+", m.group(1))
            mapping = store.get("last_brief", {})
            cleared = sum(store.resolve_by_id(mapping[n], "button") for n in numbers if n in mapping)
            bot.chat_postMessage(channel=owner_dm, thread_ts=reply_ts, text=f":white_check_mark: Cleared {cleared} item(s).")
            return

        placeholder = bot.chat_postMessage(channel=owner_dm, thread_ts=reply_ts, text="_Looking through Slack…_")
        try:
            history = thread_history(event["thread_ts"], event["ts"]) if event.get("thread_ts") else []
            answer = assistant.answer(text, history)
        except Exception as e:
            log.exception("answer failed")
            answer = f":warning: Something went wrong: {e}"
        bot.chat_update(channel=owner_dm, ts=placeholder["ts"], text=answer[:39000])

    # --- event handlers ------------------------------------------------------

    @app.event("message")
    def on_message(event, body, logger):
        if event.get("channel") == owner_dm:
            if event.get("user") == owner and not event.get("subtype"):
                handle_owner_dm(event)
            return
        # Only track messages delivered on *your* behalf (user-token events). Someone else
        # DMing the bot arrives as a bot-only event and is not addressed to you.
        if not any(not a.get("is_bot") for a in body.get("authorizations") or []):
            return
        action = tracker.on_message(event)
        if action:
            logger.debug("tracker: %s %s/%s", action, event.get("channel"), event.get("ts"))

    @app.event("reaction_added")
    def on_reaction(event):
        tracker.on_reaction(event)

    @app.action("mark_handled")
    def on_mark_handled(ack, body, client):
        ack()
        if body["user"]["id"] != owner:
            return
        item_id = int(body["actions"][0]["value"])
        store.resolve_by_id(item_id, "button")
        blocks = body["message"]["blocks"]
        for block in blocks:
            if block.get("block_id") == f"item_{item_id}":
                block.pop("accessory", None)
                block["text"]["text"] = ":white_check_mark: ~" + block["text"]["text"].split("\n")[0] + "~"
        client.chat_update(channel=body["channel"]["id"], ts=body["message"]["ts"], blocks=blocks, text=body["message"]["text"])

    def start_background() -> None:
        threading.Thread(target=backfill, args=(config, store, reader, tracker, owner_dm), daemon=True).start()
        hour, minute = (int(x) for x in config.brief_time.split(":"))
        scheduler = BackgroundScheduler(timezone=config.timezone)
        scheduler.add_job(
            send_brief, CronTrigger(day_of_week=config.brief_days, hour=hour, minute=minute, timezone=config.timezone)
        )
        scheduler.start()
        log.info("briefbot running for %s; morning brief %s %s (%s)", owner, config.brief_days, config.brief_time, config.timezone)

    return app, start_background


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config()
    config.validate()
    app, start_background = build_app(config)
    start_background()
    SocketModeHandler(app, config.app_token).start()
