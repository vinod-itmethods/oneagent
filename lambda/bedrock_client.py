"""
AWS Bedrock Client for ONEagent.
Uses Claude to extract intent from natural language workspace requests.
"""

import json
import logging
import re
import boto3
from typing import Optional

logger = logging.getLogger(__name__)

INTENT_EXTRACTION_PROMPT = """You are an assistant that extracts structured information from workspace provisioning requests.

Extract the following fields from the user's message:
- developer_type: The type of developer (backend, frontend, fullstack, devops, data, ml). If not specified, use "fullstack".
- github_repo: The GitHub repository in format "owner/repo" or full URL. Extract just "owner/repo" format.
- template: The workspace template to use (java, python, typescript, go). Infer from context if not explicitly stated:
  - "backend dev" + Java company/Spring mentioned = java
  - "backend dev" + Python/Django/Flask mentioned = python
  - "frontend dev" or React/Vue/Angular mentioned = typescript
  - "data" or "ml" mentioned = python
  - If unclear, return null
- user_mention: Any Slack user mention (format: <@U12345>) - extract just the ID.

User message: {message}

Respond with ONLY a valid JSON object, no other text:
{{"developer_type": "...", "github_repo": "...", "template": "..." or null, "user_mention": "..." or null}}
"""


class BedrockClient:
    """Client for AWS Bedrock AI services."""

    def __init__(self, region: str = "us-east-1", model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"):
        """
        Initialize Bedrock client.

        Args:
            region: AWS region for Bedrock
            model_id: Bedrock model ID to use
        """
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id

    def extract_intent(self, message: str) -> dict:
        """
        Extract workspace provisioning intent from a natural language message.

        Args:
            message: The user's Slack message

        Returns:
            Dict with extracted fields:
            - developer_type: str
            - github_repo: str or None
            - template: str or None
            - user_mention: str or None
        """
        # Clean up the message (remove bot mention)
        cleaned_message = re.sub(r"<@[A-Z0-9]+>", "", message).strip()

        prompt = INTENT_EXTRACTION_PROMPT.format(message=cleaned_message)

        try:
            response = self._invoke_claude(prompt)
            intent = self._parse_json_response(response)

            # Normalize github_repo format
            if intent.get("github_repo"):
                intent["github_repo"] = self._normalize_repo(intent["github_repo"])

            logger.info(f"Extracted intent: {intent}")
            return intent

        except Exception as e:
            logger.exception(f"Failed to extract intent: {e}")
            # Return partial extraction using regex fallback
            return self._fallback_extraction(cleaned_message)

    def _invoke_claude(self, prompt: str) -> str:
        """
        Invoke Claude model via Bedrock.

        Args:
            prompt: The prompt to send

        Returns:
            Model response text
        """
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        })

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=body,
            contentType="application/json",
            accept="application/json"
        )

        response_body = json.loads(response["body"].read())
        return response_body["content"][0]["text"]

    def _parse_json_response(self, response: str) -> dict:
        """
        Parse JSON from model response.

        Args:
            response: Model response text

        Returns:
            Parsed JSON dict
        """
        # Try to extract JSON from response
        response = response.strip()

        # Handle markdown code blocks
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]

        return json.loads(response.strip())

    def _normalize_repo(self, repo: str) -> str:
        """
        Normalize GitHub repo to owner/repo format.

        Args:
            repo: Repository string (URL or owner/repo)

        Returns:
            Normalized owner/repo format
        """
        # Handle full URLs
        if "github.com" in repo:
            # Extract owner/repo from URL
            match = re.search(r"github\.com[/:]([^/]+)/([^/\s.]+)", repo)
            if match:
                return f"{match.group(1)}/{match.group(2).rstrip('.git')}"

        # Handle owner/repo format
        if "/" in repo:
            parts = repo.strip().split("/")
            if len(parts) >= 2:
                return f"{parts[-2]}/{parts[-1].rstrip('.git')}"

        return repo

    def _fallback_extraction(self, message: str) -> dict:
        """
        Fallback extraction using regex when AI fails.

        Args:
            message: User message

        Returns:
            Extracted intent dict
        """
        intent = {
            "developer_type": "fullstack",
            "github_repo": None,
            "template": None,
            "user_mention": None
        }

        # Extract GitHub repo
        repo_patterns = [
            r"github\.com[/:]([^/\s]+/[^/\s.]+)",
            r"repo[:\s]+([^\s]+/[^\s]+)",
            r"([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)",
        ]

        for pattern in repo_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                intent["github_repo"] = match.group(1).rstrip(".git")
                break

        # Extract developer type
        if "backend" in message.lower():
            intent["developer_type"] = "backend"
        elif "frontend" in message.lower():
            intent["developer_type"] = "frontend"
        elif "devops" in message.lower():
            intent["developer_type"] = "devops"
        elif "data" in message.lower() or "ml" in message.lower():
            intent["developer_type"] = "data"

        # Extract template hint
        template_keywords = {
            "java": ["java", "spring", "maven", "gradle", "kotlin"],
            "python": ["python", "django", "flask", "fastapi", "pytorch", "tensorflow"],
            "typescript": ["typescript", "javascript", "react", "vue", "angular", "node"],
            "go": ["go", "golang"],
        }

        message_lower = message.lower()
        for template, keywords in template_keywords.items():
            if any(kw in message_lower for kw in keywords):
                intent["template"] = template
                break

        # Extract user mention
        mention_match = re.search(r"<@([A-Z0-9]+)>", message)
        if mention_match:
            intent["user_mention"] = mention_match.group(1)

        return intent
