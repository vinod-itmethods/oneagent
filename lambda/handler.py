"""
ONEagent Lambda Handler
Processes Slack app_mention events and invokes Bedrock Agent for workspace provisioning.
"""

import json
import hashlib
import hmac
import time
import os
import logging
import uuid
import boto3
from typing import Any

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Bedrock Agent configuration
AGENT_ID = "XTXHTIJ2VD"
AGENT_ALIAS_ID = "VYVNTYNNOP"

# Cache for secrets
_secrets_cache = {}


def get_secret(secret_name: str) -> str:
    """Fetch secret from AWS Secrets Manager."""
    if secret_name not in _secrets_cache:
        client = boto3.client('secretsmanager', region_name='us-east-1')
        response = client.get_secret_value(SecretId=secret_name)
        _secrets_cache[secret_name] = response['SecretString']
    return _secrets_cache[secret_name]


def verify_slack_signature(event: dict) -> bool:
    """Verify the request came from Slack using signing secret."""
    headers = event.get("headers", {})
    body = event.get("body", "")

    # Handle case-insensitive headers
    headers_lower = {k.lower(): v for k, v in headers.items()}

    timestamp = headers_lower.get("x-slack-request-timestamp", "")
    signature = headers_lower.get("x-slack-signature", "")

    try:
        signing_secret = get_secret("oneagent/slack-signing-secret")
    except Exception as e:
        logger.error(f"Failed to get signing secret: {e}")
        return False

    if not all([timestamp, signature, signing_secret]):
        logger.warning("Missing signature verification components")
        return False

    # Check timestamp to prevent replay attacks (5 min window)
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            logger.warning("Request timestamp too old")
            return False
    except ValueError:
        logger.warning("Invalid timestamp")
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{body}"
    expected_signature = "v0=" + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def handle_url_verification(body: dict) -> dict:
    """Handle Slack URL verification challenge."""
    return {
        "statusCode": 200,
        "body": json.dumps({"challenge": body.get("challenge")})
    }


def send_slack_message(channel: str, text: str, thread_ts: str = None) -> dict:
    """Send a message to Slack."""
    import requests

    slack_token = get_secret("oneagent/slack-bot-token")

    payload = {
        "channel": channel,
        "text": text
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {slack_token}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=10
    )
    return response.json()


def invoke_bedrock_agent(user_message: str, channel: str, thread_ts: str) -> str:
    """Invoke the Bedrock Agent with the user's message."""
    client = boto3.client('bedrock-agent-runtime', region_name='us-east-1')

    # Create a unique session ID
    session_id = str(uuid.uuid4())

    # Add context to the message
    enhanced_message = f"""User request from Slack channel {channel}:
{user_message}

When done, send a summary message to Slack channel {channel} with thread_ts {thread_ts}."""

    try:
        response = client.invoke_agent(
            agentId=AGENT_ID,
            agentAliasId=AGENT_ALIAS_ID,
            sessionId=session_id,
            inputText=enhanced_message
        )

        # Process the streaming response
        completion = ""
        for event in response.get('completion', []):
            if 'chunk' in event:
                chunk = event['chunk']
                if 'bytes' in chunk:
                    completion += chunk['bytes'].decode('utf-8')

        logger.info(f"Agent response: {completion}")
        return completion

    except Exception as e:
        logger.exception(f"Error invoking Bedrock Agent: {e}")
        return f"Error: {str(e)}"


def handle_app_mention(event_data: dict) -> dict:
    """Process app_mention event using Bedrock Agent."""
    channel = event_data.get("channel")
    user = event_data.get("user")
    text = event_data.get("text", "")
    thread_ts = event_data.get("thread_ts") or event_data.get("ts")

    logger.info(f"Processing mention from user {user}: {text}")

    try:
        # Send acknowledgement
        send_slack_message(
            channel=channel,
            text="Processing your request with ONEagent...",
            thread_ts=thread_ts
        )

        # Invoke Bedrock Agent
        agent_response = invoke_bedrock_agent(text, channel, thread_ts)

        # If agent didn't send a Slack message, send the response
        if agent_response and "error" not in agent_response.lower():
            send_slack_message(
                channel=channel,
                text=f"Agent completed: {agent_response[:500]}",
                thread_ts=thread_ts
            )

        return {"statusCode": 200, "body": "OK"}

    except Exception as e:
        logger.exception("Error processing workspace request")
        send_slack_message(
            channel=channel,
            text=f"Sorry, I encountered an error: {str(e)}",
            thread_ts=thread_ts
        )
        return {"statusCode": 200, "body": "OK"}


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda entry point."""
    logger.info(f"Received event: {json.dumps(event)}")

    # Parse body
    body = event.get("body", "{}")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {}

    # Handle URL verification (Slack setup) - no signature check needed
    if body.get("type") == "url_verification":
        return handle_url_verification(body)

    # Verify Slack signature for all other requests
    if not verify_slack_signature(event):
        logger.warning("Invalid Slack signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    # Handle events
    event_callback = body.get("event", {})
    event_type = event_callback.get("type")

    if event_type == "app_mention":
        return handle_app_mention(event_callback)

    return {"statusCode": 200, "body": "OK"}
