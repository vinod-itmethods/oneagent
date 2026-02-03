"""
Coder API Client for ONEagent.
Handles workspace provisioning and template management.
"""

import requests
import logging
from typing import Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class CoderClient:
    """Client for interacting with Coder API."""

    def __init__(self, base_url: str, api_token: str):
        """
        Initialize Coder client.

        Args:
            base_url: Coder instance URL (e.g., https://coder.example.com)
            api_token: Coder API token
        """
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.headers = {
            "Coder-Session-Token": api_token,
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Make an authenticated request to Coder API.

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional request arguments

        Returns:
            JSON response
        """
        url = urljoin(self.base_url, f"/api/v2{endpoint}")

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                timeout=30,
                **kwargs
            )
            response.raise_for_status()
            return response.json() if response.content else {}

        except requests.RequestException as e:
            logger.exception(f"Coder API request failed: {e}")
            raise

    def list_templates(self, organization: str = "default") -> list:
        """
        List available workspace templates.

        Args:
            organization: Organization ID or name

        Returns:
            List of template objects
        """
        response = self._request("GET", f"/organizations/{organization}/templates")
        return response if isinstance(response, list) else []

    def get_template(self, template_id: str) -> dict:
        """
        Get template details by ID.

        Args:
            template_id: Template UUID

        Returns:
            Template object
        """
        return self._request("GET", f"/templates/{template_id}")

    def get_template_by_name(self, name: str, organization: str = "default") -> Optional[dict]:
        """
        Get template by name.

        Args:
            name: Template name
            organization: Organization ID or name

        Returns:
            Template object or None
        """
        templates = self.list_templates(organization)
        return next((t for t in templates if t["name"] == name), None)

    def create_workspace(
        self,
        template_id: str,
        name: str,
        parameters: Optional[dict] = None,
        organization: str = "default",
        user: str = "me"
    ) -> dict:
        """
        Create a new workspace from a template.

        Args:
            template_id: Template UUID
            name: Workspace name
            parameters: Template parameters (rich_parameter_values)
            organization: Organization ID
            user: User ID or "me"

        Returns:
            Created workspace object
        """
        # Get template version for latest
        template = self.get_template(template_id)
        template_version_id = template.get("active_version_id")

        payload = {
            "name": name,
            "template_id": template_id,
            "template_version_id": template_version_id,
        }

        # Add parameters if provided
        if parameters:
            payload["rich_parameter_values"] = [
                {"name": k, "value": str(v)}
                for k, v in parameters.items()
            ]

        return self._request(
            "POST",
            f"/organizations/{organization}/members/{user}/workspaces",
            json=payload
        )

    def get_workspace(self, workspace_id: str) -> dict:
        """
        Get workspace details.

        Args:
            workspace_id: Workspace UUID

        Returns:
            Workspace object
        """
        return self._request("GET", f"/workspaces/{workspace_id}")

    def get_workspace_by_name(self, owner: str, name: str) -> Optional[dict]:
        """
        Get workspace by owner and name.

        Args:
            owner: Workspace owner username
            name: Workspace name

        Returns:
            Workspace object or None
        """
        try:
            return self._request("GET", f"/users/{owner}/workspace/{name}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def start_workspace(self, workspace_id: str) -> dict:
        """
        Start a stopped workspace.

        Args:
            workspace_id: Workspace UUID

        Returns:
            Build object
        """
        workspace = self.get_workspace(workspace_id)
        template_version_id = workspace.get("latest_build", {}).get("template_version_id")

        return self._request(
            "POST",
            f"/workspaces/{workspace_id}/builds",
            json={
                "template_version_id": template_version_id,
                "transition": "start"
            }
        )

    def stop_workspace(self, workspace_id: str) -> dict:
        """
        Stop a running workspace.

        Args:
            workspace_id: Workspace UUID

        Returns:
            Build object
        """
        workspace = self.get_workspace(workspace_id)
        template_version_id = workspace.get("latest_build", {}).get("template_version_id")

        return self._request(
            "POST",
            f"/workspaces/{workspace_id}/builds",
            json={
                "template_version_id": template_version_id,
                "transition": "stop"
            }
        )

    def delete_workspace(self, workspace_id: str) -> dict:
        """
        Delete a workspace.

        Args:
            workspace_id: Workspace UUID

        Returns:
            Build object
        """
        workspace = self.get_workspace(workspace_id)
        template_version_id = workspace.get("latest_build", {}).get("template_version_id")

        return self._request(
            "POST",
            f"/workspaces/{workspace_id}/builds",
            json={
                "template_version_id": template_version_id,
                "transition": "delete",
                "orphan": False
            }
        )

    def get_current_user(self) -> dict:
        """
        Get the current authenticated user.

        Returns:
            User object
        """
        return self._request("GET", "/users/me")

    def list_workspaces(self, owner: str = "me") -> list:
        """
        List workspaces for a user.

        Args:
            owner: User ID or "me"

        Returns:
            List of workspace objects
        """
        response = self._request("GET", f"/workspaces?owner={owner}")
        return response.get("workspaces", [])
