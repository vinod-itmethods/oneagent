# Brief — your private Slack assistant

A small Slack app that works for **one person: you**. It:

- **Tracks every message addressed to you**: DMs, group DMs, @mentions (including your user groups), and replies in threads you started or posted in.
- **Knows when you've responded**: you replied in the thread or DM, reacted with an emoji, or pressed **Handled**.
- **Sends you a morning brief** (default 8:30 on weekdays) of everything still waiting on you, with Claude's take on what needs you first, plus optional highlights from channels you pick.
- **Answers questions about your Slack**. DM it things like *"What did Priya ask me about the Q4 budget?"* or *"Summarize #eng-incidents since Monday"*. It searches and reads your channels, DMs and threads, then answers with links to the source messages.

```
 you ──DM──▶  Brief bot ──▶ Claude (tools: search, read channel, read thread, awaiting-reply list)
                 ▲  │
  Slack events ──┘  └──▶ SQLite: what's waiting on you, which threads you're in
 (your messages, via
  your user token)
```

It runs as one Python process using **Socket Mode**, so you don't need a public URL, a load balancer or AWS. Run it on your laptop, a small VM or in a container.

---

## Setup (about 10 minutes)

### 1. Create the Slack app

1. Go to <https://api.slack.com/apps> → **Create New App** → **From a manifest** → pick your workspace.
2. Paste [`slack-manifest.yaml`](slack-manifest.yaml) → **Create**.
3. **Basic Information → App-Level Tokens → Generate Token and Scopes**: add the scope `connections:write`. Copy the `xapp-…` token.
4. **Install App → Install to Workspace** and approve. If your workspace needs admin approval for apps, request it here.
5. **OAuth & Permissions**: copy the **Bot User OAuth Token** (`xoxb-…`) and the **User OAuth Token** (`xoxp-…`).

> The **user token** is what lets the bot see your DMs and channels. It acts as you, so treat it like a password. The bot only *reads* with it, and it only ever posts in its own DM with you.

### 2. Configure

```bash
cd briefbot
cp .env.example .env     # then fill in the three Slack tokens and your ANTHROPIC_API_KEY
```

To use Claude through **Amazon Bedrock** instead of the Anthropic API, set `CLAUDE_PROVIDER=bedrock` and `AWS_REGION`. It then uses your normal AWS credentials.

### 3. Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m briefbot
```

Or with Docker:

```bash
docker build -t briefbot .
docker run -d --name briefbot --env-file .env -v briefbot-data:/data --restart unless-stopped briefbot
```

On first start it catches up on the last `BACKFILL_DAYS` (default 3) so your first brief isn't empty. After that, live events keep it current.

### 4. Try it

Open the **Brief** app in Slack (in the sidebar under *Apps*) and send:

| You type | What happens |
|---|---|
| `brief` / `catch me up` | Brief right now |
| `done 2 5` | Clear items 2 and 5 from the last brief |
| any question | Searches your Slack and answers in a thread. Follow-ups in that thread keep the context |
| `help` | Shows the commands |

---

## What counts as "waiting on you"

| Message | Tracked? | Cleared when you… |
|---|---|---|
| DM / group DM to you | ✅ | post in that DM after it, or reply in its thread |
| @mention of you or your user group | ✅ | reply in its thread, or post in the channel @mentioning the person |
| Reply in a thread you started or posted in | ✅ | reply in that thread |
| Ordinary channel chatter | ❌ | (use `HIGHLIGHT_CHANNELS` to get it summarized) |
| Bot or integration messages | ❌ by default (`INCLUDE_BOT_MESSAGES=true` to track them) | |
| Anything | | react with any emoji (`REACTION_COUNTS_AS_REPLY`), or press **Handled** |

Items older than `MAX_AGE_DAYS` (default 14) drop off the brief.

## Configuration

All settings are environment variables. See [`.env.example`](.env.example) for the full list with comments. The ones you'll most likely change:

- `TIMEZONE`, `BRIEF_TIME`, `BRIEF_DAYS`: when the brief arrives (`BRIEF_DAYS` uses cron syntax such as `mon-fri` or `mon,wed,fri`)
- `HIGHLIGHT_CHANNELS`: channels to summarize in the brief, e.g. `#announcements,#eng-incidents`
- `OWNER_USERGROUP_IDS`: your user groups, so `@platform-team` pings count
- `CLAUDE_MODEL` / `CLAUDE_EFFORT`: defaults are `claude-opus-5-5` / `medium`. Use `low` for faster, cheaper answers, or `high` for deeper digging.

## Privacy and security

- **One owner.** The owner is whoever the user token belongs to. Anyone else who DMs the bot is ignored, and the "Handled" buttons only work for you.
- **Read-only access to your data.** The user token's scopes are all `*:read` / `*:history` / `search:read`. The bot posts only in its DM with you, using the bot token.
- **What leaves Slack.** Message text the bot looks at is sent to Claude (the Anthropic API, or Bedrock in your AWS account) to write the brief and answer your questions. Check that this fits your company's policy before connecting a work Slack.
- **What's stored.** The SQLite file stores the text of messages that are waiting on you, plus thread IDs you've taken part in. Nothing else is stored. Delete the file to reset.
- Keep `.env` out of git (it's in `.gitignore`).

## Project layout

```
briefbot/
├── app.py           Slack wiring: events, DM commands, Handled button, scheduler
├── tracker.py       What's addressed to you, and when you've answered
├── store.py         SQLite
├── brief.py         Builds the morning brief (Block Kit)
├── assistant.py     Claude: Q&A tool loop + brief summary
├── slack_reader.py  Read-only Slack access with your user token
├── backfill.py      One-time catch-up on first start
└── config.py        Settings
tests/               python -m unittest discover -s tests
```

## Troubleshooting

- **The bot never sees my messages.** Check that the app has a **User OAuth Token** and that `user_events` are subscribed (Event Subscriptions page). Reinstall the app after you change scopes.
- **`not_allowed_token_type` or `missing_scope`.** Reinstall the app from *Install App*. The tokens change when scopes change, so update `.env` too.
- **The brief time is wrong.** Set `TIMEZONE` to an IANA name such as `America/Toronto` or `Asia/Kolkata`.
- **Rate-limit warnings during the first-start catch-up** are normal if you have many DMs. The client retries automatically.
