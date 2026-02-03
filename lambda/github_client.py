"""
GitHub API Client for ONEagent.
Validates repositories and fetches metadata.
"""

import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Client for interacting with GitHub API."""

    def __init__(self, token: Optional[str] = None):
        """
        Initialize GitHub client.

        Args:
            token: GitHub Personal Access Token (optional for public repos)
        """
        self.token = token
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def get_repo_info(self, repo: str) -> Optional[dict]:
        """
        Get repository information.

        Args:
            repo: Repository in owner/repo format

        Returns:
            Repository info dict or None if not found
        """
        try:
            response = requests.get(
                f"{GITHUB_API_BASE}/repos/{repo}",
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 404:
                logger.warning(f"Repository not found: {repo}")
                return None

            response.raise_for_status()
            data = response.json()

            return {
                "name": data["name"],
                "full_name": data["full_name"],
                "description": data.get("description"),
                "private": data["private"],
                "clone_url": data["clone_url"],
                "ssh_url": data["ssh_url"],
                "default_branch": data["default_branch"],
                "language": data.get("language"),
                "topics": data.get("topics", []),
                "size": data["size"],
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
            }

        except requests.RequestException as e:
            logger.exception(f"Failed to get repo info: {e}")
            return None

    def get_repo_languages(self, repo: str) -> dict:
        """
        Get repository language breakdown.

        Args:
            repo: Repository in owner/repo format

        Returns:
            Dict of language -> bytes
        """
        try:
            response = requests.get(
                f"{GITHUB_API_BASE}/repos/{repo}/languages",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            logger.exception(f"Failed to get repo languages: {e}")
            return {}

    def get_primary_language(self, repo: str) -> Optional[str]:
        """
        Get the primary language of a repository.

        Args:
            repo: Repository in owner/repo format

        Returns:
            Primary language name or None
        """
        languages = self.get_repo_languages(repo)
        if languages:
            return max(languages, key=languages.get)
        return None

    def validate_repo_access(self, repo: str) -> bool:
        """
        Check if the repository is accessible.

        Args:
            repo: Repository in owner/repo format

        Returns:
            True if accessible, False otherwise
        """
        try:
            response = requests.get(
                f"{GITHUB_API_BASE}/repos/{repo}",
                headers=self.headers,
                timeout=10
            )
            return response.status_code == 200

        except requests.RequestException:
            return False

    def get_default_branch(self, repo: str) -> Optional[str]:
        """
        Get the default branch of a repository.

        Args:
            repo: Repository in owner/repo format

        Returns:
            Default branch name or None
        """
        info = self.get_repo_info(repo)
        return info.get("default_branch") if info else None

    def check_file_exists(self, repo: str, path: str, ref: Optional[str] = None) -> bool:
        """
        Check if a file exists in the repository.

        Args:
            repo: Repository in owner/repo format
            path: File path in repository
            ref: Git ref (branch/tag/commit), defaults to default branch

        Returns:
            True if file exists
        """
        try:
            params = {"ref": ref} if ref else {}
            response = requests.get(
                f"{GITHUB_API_BASE}/repos/{repo}/contents/{path}",
                headers=self.headers,
                params=params,
                timeout=10
            )
            return response.status_code == 200

        except requests.RequestException:
            return False

    def detect_project_type(self, repo: str) -> Optional[str]:
        """
        Detect the project type based on configuration files.

        Args:
            repo: Repository in owner/repo format

        Returns:
            Project type: java, python, typescript, go, or None
        """
        # Check for common project files
        checks = [
            ("pom.xml", "java"),
            ("build.gradle", "java"),
            ("build.gradle.kts", "java"),
            ("pyproject.toml", "python"),
            ("setup.py", "python"),
            ("requirements.txt", "python"),
            ("package.json", "typescript"),
            ("go.mod", "go"),
            ("Cargo.toml", "rust"),
        ]

        for file_path, project_type in checks:
            if self.check_file_exists(repo, file_path):
                return project_type

        # Fall back to primary language
        language = self.get_primary_language(repo)
        if language:
            language_map = {
                "Java": "java",
                "Kotlin": "java",
                "Python": "python",
                "JavaScript": "typescript",
                "TypeScript": "typescript",
                "Go": "go",
                "Rust": "rust",
            }
            return language_map.get(language)

        return None
