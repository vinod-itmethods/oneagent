"""
Bedrock Agent Action Group Handlers
Handles GitHub and Coder actions for the ONEagent Bedrock Agent.
"""

import json
import os
import logging
import boto3
import requests
from typing import Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Cache for secrets
_secrets_cache = {}


def get_secret(secret_name: str) -> str:
    """Fetch secret from AWS Secrets Manager."""
    if secret_name not in _secrets_cache:
        client = boto3.client('secretsmanager', region_name='us-east-1')
        response = client.get_secret_value(SecretId=secret_name)
        _secrets_cache[secret_name] = response['SecretString']
    return _secrets_cache[secret_name]


def github_get_repo_info(owner: str, repo: str) -> dict:
    """Get GitHub repository information."""
    token = get_secret("oneagent/github-token")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}" if token != "placeholder-token" else None
    }
    headers = {k: v for k, v in headers.items() if v}

    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
            timeout=10
        )

        if response.status_code == 404:
            return {"error": f"Repository {owner}/{repo} not found"}

        response.raise_for_status()
        data = response.json()

        return {
            "name": data["name"],
            "full_name": data["full_name"],
            "description": data.get("description", ""),
            "language": data.get("language", "unknown"),
            "default_branch": data["default_branch"],
            "clone_url": data["clone_url"],
            "private": data["private"]
        }
    except Exception as e:
        logger.exception(f"Error fetching repo: {e}")
        return {"error": str(e)}


def github_validate_repo(owner: str, repo: str) -> dict:
    """Validate if a GitHub repository exists and is accessible."""
    info = github_get_repo_info(owner, repo)
    if "error" in info:
        return {"valid": False, "error": info["error"]}
    return {"valid": True, "repo_info": info}


def coder_list_templates() -> dict:
    """List available Coder templates."""
    coder_url = get_secret("oneagent/coder-url")
    coder_token = get_secret("oneagent/coder-api-token")

    if coder_token == "placeholder-token":
        return {"error": "Coder is not configured yet", "templates": []}

    try:
        response = requests.get(
            f"{coder_url}/api/v2/organizations/default/templates",
            headers={"Coder-Session-Token": coder_token},
            timeout=10
        )
        response.raise_for_status()
        templates = response.json()
        return {
            "templates": [{"name": t["name"], "id": t["id"]} for t in templates]
        }
    except Exception as e:
        logger.exception(f"Error listing templates: {e}")
        return {"error": str(e), "templates": []}


def coder_create_workspace(template_name: str, workspace_name: str, git_repo_url: str, git_branch: str = "main") -> dict:
    """Create a Coder workspace."""
    coder_url = get_secret("oneagent/coder-url")
    coder_token = get_secret("oneagent/coder-api-token")

    if coder_token == "placeholder-token":
        return {"error": "Coder is not configured yet"}

    try:
        # First get template ID
        templates_response = requests.get(
            f"{coder_url}/api/v2/organizations/default/templates",
            headers={"Coder-Session-Token": coder_token},
            timeout=10
        )
        templates_response.raise_for_status()
        templates = templates_response.json()

        template = next((t for t in templates if t["name"] == template_name), None)
        if not template:
            return {"error": f"Template '{template_name}' not found"}

        # Get template version
        template_detail = requests.get(
            f"{coder_url}/api/v2/templates/{template['id']}",
            headers={"Coder-Session-Token": coder_token},
            timeout=10
        ).json()

        # Create workspace
        payload = {
            "name": workspace_name,
            "template_id": template["id"],
            "template_version_id": template_detail["active_version_id"],
            "rich_parameter_values": [
                {"name": "git_repo_url", "value": git_repo_url},
                {"name": "git_branch", "value": git_branch}
            ]
        }

        response = requests.post(
            f"{coder_url}/api/v2/organizations/default/members/me/workspaces",
            headers={"Coder-Session-Token": coder_token, "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        workspace = response.json()

        workspace_url = f"{coder_url}/@{workspace.get('owner_name', 'me')}/{workspace['name']}"

        return {
            "success": True,
            "workspace_name": workspace["name"],
            "workspace_url": workspace_url,
            "template": template_name
        }
    except Exception as e:
        logger.exception(f"Error creating workspace: {e}")
        return {"error": str(e)}


def send_slack_message(channel: str, message: str, thread_ts: Optional[str] = None) -> dict:
    """Send a message to Slack."""
    slack_token = get_secret("oneagent/slack-bot-token")

    payload = {
        "channel": channel,
        "text": message
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    try:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {slack_token}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10
        )
        data = response.json()
        return {"success": data.get("ok", False), "ts": data.get("ts")}
    except Exception as e:
        logger.exception(f"Error sending Slack message: {e}")
        return {"success": False, "error": str(e)}


def lambda_handler(event, context):
    """
    Bedrock Agent Action Group Lambda Handler.
    Routes to appropriate function based on action group and function name.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    agent = event.get('agent', {})
    action_group = event.get('actionGroup', '')
    function_name = event.get('function', '')
    parameters = event.get('parameters', [])

    # Convert parameters list to dict
    params = {p['name']: p['value'] for p in parameters}

    logger.info(f"Action: {action_group}/{function_name}, Params: {params}")

    result = {}

    try:
        if function_name == "github_get_repo_info":
            result = github_get_repo_info(params.get('owner'), params.get('repo'))

        elif function_name == "github_validate_repo":
            result = github_validate_repo(params.get('owner'), params.get('repo'))

        elif function_name == "coder_list_templates":
            result = coder_list_templates()

        elif function_name == "coder_create_workspace":
            result = coder_create_workspace(
                template_name=params.get('template_name'),
                workspace_name=params.get('workspace_name'),
                git_repo_url=params.get('git_repo_url'),
                git_branch=params.get('git_branch', 'main')
            )

        elif function_name == "send_slack_message":
            result = send_slack_message(
                channel=params.get('channel'),
                message=params.get('message'),
                thread_ts=params.get('thread_ts')
            )

        else:
            result = {"error": f"Unknown function: {function_name}"}

    except Exception as e:
        logger.exception(f"Error executing {function_name}")
        result = {"error": str(e)}

    # Format response for Bedrock Agent
    response_body = {
        "TEXT": {
            "body": json.dumps(result)
        }
    }

    action_response = {
        "actionGroup": action_group,
        "function": function_name,
        "functionResponse": {
            "responseBody": response_body
        }
    }

    return {
        "messageVersion": "1.0",
        "response": action_response
    }
