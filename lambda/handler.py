"""
ONEagent Lambda Handler
Processes Slack app_mention events and provisions Coder workspaces.
"""

import json
import hashlib
import hmac
import time
import os
import logging
from typing import Any

from slack_client import SlackClient
from bedrock_client import BedrockClient
from coder_client import CoderClient
from github_client import GitHubClient

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients (will be configured via environment/secrets)
slack_client = None
bedrock_client = None
coder_client = None
github_client = None


def verify_slack_signature(event: dict) -> bool:
    """Verify the request came from Slack using signing secret."""
    headers = event.get("headers", {})
    body = event.get("body", "")

    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")

    if not all([timestamp, signature, signing_secret]):
        logger.warning("Missing signature verification components")
        return False

    # Check timestamp to prevent replay attacks (5 min window)
    if abs(time.time() - int(timestamp)) > 60 * 5:
        logger.warning("Request timestamp too old")
        return False

    # Compute expected signature
    sig_basestring = f"v0:{timestamp}:{body}"
    expected_signature = "v0=" + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def initialize_clients():
    """Initialize API clients with secrets from environment/Secrets Manager."""
    global slack_client, bedrock_client, coder_client, github_client

    # In production, fetch from AWS Secrets Manager
    # For now, use environment variables
    slack_client = SlackClient(
        bot_token=os.environ.get("SLACK_BOT_TOKEN"),
    )

    bedrock_client = BedrockClient(
        region=os.environ.get("AWS_REGION", "us-east-1"),
        model_id=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
    )

    coder_client = CoderClient(
        base_url=os.environ.get("CODER_URL"),
        api_token=os.environ.get("CODER_API_TOKEN")
    )

    github_client = GitHubClient(
        token=os.environ.get("GITHUB_TOKEN")
    )


def handle_url_verification(body: dict) -> dict:
    """Handle Slack URL verification challenge."""
    return {
        "statusCode": 200,
        "body": json.dumps({"challenge": body.get("challenge")})
    }


def handle_app_mention(event_data: dict) -> dict:
    """Process app_mention event and provision workspace."""
    channel = event_data.get("channel")
    user = event_data.get("user")
    text = event_data.get("text", "")
    thread_ts = event_data.get("thread_ts") or event_data.get("ts")

    logger.info(f"Processing mention from user {user}: {text}")

    try:
        # Acknowledge receipt
        slack_client.post_message(
            channel=channel,
            text="Processing your workspace request...",
            thread_ts=thread_ts
        )

        # Extract intent using Bedrock
        intent = bedrock_client.extract_intent(text)
        logger.info(f"Extracted intent: {intent}")

        if not intent.get("github_repo"):
            slack_client.post_message(
                channel=channel,
                text="I couldn't identify a GitHub repository in your request. Please specify a repo like: `@ONEagent onboard dev for repo owner/repo-name`",
                thread_ts=thread_ts
            )
            return {"statusCode": 200, "body": "OK"}

        # Validate GitHub repo exists
        repo_info = github_client.get_repo_info(intent["github_repo"])
        if not repo_info:
            slack_client.post_message(
                channel=channel,
                text=f"Repository `{intent['github_repo']}` not found or not accessible.",
                thread_ts=thread_ts
            )
            return {"statusCode": 200, "body": "OK"}

        # Determine template
        template_name = intent.get("template")
        if not template_name:
            # Infer from repo language
            template_name = infer_template_from_repo(repo_info)

        # Check if template exists
        templates = coder_client.list_templates()
        template = next((t for t in templates if t["name"] == template_name), None)

        if not template:
            available = ", ".join([t["name"] for t in templates])
            slack_client.post_message(
                channel=channel,
                text=f"Template `{template_name}` not found. Available templates: {available}",
                thread_ts=thread_ts
            )
            return {"statusCode": 200, "body": "OK"}

        # Get Slack user info for workspace naming
        slack_user_info = slack_client.get_user_info(user)
        workspace_name = generate_workspace_name(
            slack_user_info.get("name", user),
            repo_info["name"]
        )

        # Create workspace
        workspace = coder_client.create_workspace(
            template_id=template["id"],
            name=workspace_name,
            parameters={
                "git_repo_url": repo_info["clone_url"],
                "git_branch": repo_info.get("default_branch", "main"),
            }
        )

        # Post success message with workspace URL
        workspace_url = f"{os.environ.get('CODER_URL')}/@{workspace['owner_name']}/{workspace['name']}"

        slack_client.post_message(
            channel=channel,
            text=f"Workspace created successfully!\n\n"
                 f"*Workspace:* `{workspace_name}`\n"
                 f"*Template:* `{template_name}`\n"
                 f"*Repository:* `{intent['github_repo']}`\n"
                 f"*URL:* {workspace_url}",
            thread_ts=thread_ts
        )

        return {"statusCode": 200, "body": "OK"}

    except Exception as e:
        logger.exception("Error processing workspace request")
        slack_client.post_message(
            channel=channel,
            text=f"Sorry, I encountered an error: {str(e)}",
            thread_ts=thread_ts
        )
        return {"statusCode": 200, "body": "OK"}


def infer_template_from_repo(repo_info: dict) -> str:
    """Infer the appropriate template from repository metadata."""
    language = repo_info.get("language", "").lower()

    language_to_template = {
        "java": "java",
        "kotlin": "java",
        "python": "python",
        "javascript": "typescript",
        "typescript": "typescript",
        "go": "go",
    }

    return language_to_template.get(language, "python")


def generate_workspace_name(username: str, repo_name: str) -> str:
    """Generate a valid workspace name."""
    # Coder workspace names: lowercase, alphanumeric, hyphens
    name = f"{username}-{repo_name}".lower()
    name = "".join(c if c.isalnum() or c == "-" else "-" for c in name)
    name = name.strip("-")[:32]  # Max length
    return name


def lambda_handler(event: dict, context: Any) -> dict:
    """Main Lambda entry point."""
    logger.info(f"Received event: {json.dumps(event)}")

    # Initialize clients on cold start
    if slack_client is None:
        initialize_clients()

    # Parse body
    body = event.get("body", "{}")
    if isinstance(body, str):
        body = json.loads(body)

    # Handle URL verification (Slack setup)
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
        # Respond immediately to Slack (3 second timeout)
        # Process asynchronously in production
        return handle_app_mention(event_callback)

    return {"statusCode": 200, "body": "OK"}
