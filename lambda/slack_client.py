"""
Slack API Client for ONEagent.
Handles posting messages and fetching user information.
"""

import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackClient:
    """Client for interacting with Slack API."""

    def __init__(self, bot_token: str):
        """
        Initialize Slack client.

        Args:
            bot_token: Slack Bot OAuth token (xoxb-...)
        """
        self.bot_token = bot_token
        self.headers = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json"
        }

    def post_message(
        self,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        blocks: Optional[list] = None
    ) -> dict:
        """
        Post a message to a Slack channel.

        Args:
            channel: Channel ID to post to
            text: Message text (fallback for notifications)
            thread_ts: Thread timestamp to reply in thread
            blocks: Rich message blocks (optional)

        Returns:
            Slack API response
        """
        payload = {
            "channel": channel,
            "text": text,
        }

        if thread_ts:
            payload["thread_ts"] = thread_ts

        if blocks:
            payload["blocks"] = blocks

        try:
            response = requests.post(
                f"{SLACK_API_BASE}/chat.postMessage",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                logger.error(f"Slack API error: {data.get('error')}")

            return data

        except requests.RequestException as e:
            logger.exception(f"Failed to post Slack message: {e}")
            raise

    def get_user_info(self, user_id: str) -> dict:
        """
        Get information about a Slack user.

        Args:
            user_id: Slack user ID

        Returns:
            User information dict
        """
        try:
            response = requests.get(
                f"{SLACK_API_BASE}/users.info",
                headers=self.headers,
                params={"user": user_id},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if data.get("ok"):
                return data.get("user", {})
            else:
                logger.error(f"Failed to get user info: {data.get('error')}")
                return {}

        except requests.RequestException as e:
            logger.exception(f"Failed to get Slack user info: {e}")
            return {}

    def post_interactive_message(
        self,
        channel: str,
        text: str,
        options: list,
        action_id: str,
        thread_ts: Optional[str] = None
    ) -> dict:
        """
        Post an interactive message with buttons/select menu.

        Args:
            channel: Channel ID
            text: Message text
            options: List of options [{"text": "Java", "value": "java"}, ...]
            action_id: Unique action identifier
            thread_ts: Thread timestamp

        Returns:
            Slack API response
        """
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "static_select",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "Select a template"
                        },
                        "action_id": action_id,
                        "options": [
                            {
                                "text": {
                                    "type": "plain_text",
                                    "text": opt["text"]
                                },
                                "value": opt["value"]
                            }
                            for opt in options
                        ]
                    }
                ]
            }
        ]

        return self.post_message(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
            blocks=blocks
        )

    def update_message(
        self,
        channel: str,
        ts: str,
        text: str,
        blocks: Optional[list] = None
    ) -> dict:
        """
        Update an existing message.

        Args:
            channel: Channel ID
            ts: Message timestamp to update
            text: New message text
            blocks: New message blocks (optional)

        Returns:
            Slack API response
        """
        payload = {
            "channel": channel,
            "ts": ts,
            "text": text,
        }

        if blocks:
            payload["blocks"] = blocks

        try:
            response = requests.post(
                f"{SLACK_API_BASE}/chat.update",
                headers=self.headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            logger.exception(f"Failed to update Slack message: {e}")
            raise
