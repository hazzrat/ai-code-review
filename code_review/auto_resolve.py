"""Auto-resolve functionality for code review comments.

When a PR is updated and previously flagged issues are fixed,
this module automatically resolves the corresponding review comments.
"""

import json
import subprocess
from typing import Optional


class AutoResolver:
    """Manages auto-resolution of review comments."""

    def __init__(self, pr_url: str):
        self.pr_url = pr_url
        self.owner, self.repo, self.pr_number = self._parse_url(pr_url)
        self._comment_store = {}

    def _parse_url(self, url: str) -> tuple[str, str, int]:
        """Parse PR URL into components."""
        from urllib.parse import urlparse

        if url.startswith("http"):
            parsed = urlparse(url)
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 4 and parts[2] == "pull":
                return parts[0], parts[1], int(parts[3])
        elif "#" in url:
            repo, num = url.split("#")
            owner, repo_name = repo.split("/")
            return owner, repo_name, int(num)

        raise ValueError(f"Invalid PR URL: {url}")

    def _run_gh(self, args: list[str], check: bool = True) -> str:
        """Run gh CLI command."""
        cmd = ["gh"] + args
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"gh command failed: {result.stderr}")
        return result.stdout

    def store_comment(self, comment_id: int, file: str, line: int, finding_hash: str) -> None:
        """Store a comment for later auto-resolution."""
        self._comment_store[comment_id] = {
            "file": file,
            "line": line,
            "finding_hash": finding_hash,
        }

    def get_existing_review_comments(self, per_page: int = 100, max_pages: int = 10) -> list[dict]:
        """Get all review comments from the current PR review with pagination.

        Args:
            per_page: Number of comments per page (max 100)
            max_pages: Maximum number of pages to fetch
        """
        all_comments = []
        page = 1

        while page <= max_pages:
            result = self._run_gh([
                "api",
                f"repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/comments",
                "-f", f"per_page={per_page}",
                "-f", f"page={page}",
            ], check=False)

            if not result.strip():
                break

            comments = json.loads(result)
            if not isinstance(comments, list):
                break

            all_comments.extend(comments)

            # If we got fewer than per_page, we've reached the end
            if len(comments) < per_page:
                break

            page += 1

        return all_comments

    def get_pr_review(self) -> Optional[dict]:
        """Get the current PR review if one exists."""
        # Check if we have an existing review
        result = self._run_gh([
            "api",
            f"repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/reviews",
            "-f", "state=COMMENTED",
            "-f", f"author={self.owner}",
        ], check=False)

        reviews = json.loads(result) if result.strip() else []
        # Find our bot's review
        for review in reviews:
            if review.get("user", {}).get("login") == "github-actions[bot]":
                return review
        return None

    def resolve_comment(self, comment_id: int) -> bool:
        """Resolve a single review comment."""
        try:
            self._run_gh([
                "api",
                "--method", "POST",
                f"repos/{self.owner}/{self.repo}/pulls/comments/{comment_id}/reactions",
                "-f", "content=+1",
            ], check=False)
            return True
        except Exception:
            return False

    def check_and_resolve_fixed(
        self,
        previous_findings: list[dict],
        current_diff: str,
    ) -> int:
        """Check if previously flagged issues are fixed and resolve comments.

        Args:
            previous_findings: List of previous findings with comment IDs
            current_diff: The current diff text

        Returns:
            Number of comments resolved
        """
        resolved_count = 0

        for finding in previous_findings:
            file = finding.get("file", "")
            line = finding.get("line", 0)
            comment_id = finding.get("comment_id")

            if not comment_id:
                continue

            # Check if the line was modified or removed in the current diff
            if self._is_line_fixed(file, line, current_diff):
                if self.resolve_comment(comment_id):
                    resolved_count += 1

        return resolved_count

    def _is_line_fixed(self, file: str, line: int, diff_text: str) -> bool:
        """Check if a specific line was modified/removed in the diff."""
        # Parse diff to find if the line was changed
        current_file = None
        for diff_line in diff_text.split("\n"):
            if diff_line.startswith("diff --git "):
                parts = diff_line.split(" ")
                current_file = parts[2][2:] if len(parts) > 2 else None
            elif current_file == file and diff_line.startswith("@@"):
                # Check if line falls within changed range
                import re
                match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff_line)
                if match:
                    new_start = int(match.group(1))
                    new_count = int(match.group(2) or 1)
                    if new_start <= line <= new_start + new_count:
                        return True
            elif current_file == file and diff_line.startswith("-"):
                # Line was deleted
                return True

        return False

    def auto_resolve_all_fixed(self, current_diff: str) -> tuple[int, int]:
        """Auto-resolve all fixed issues.

        Returns:
            Tuple of (resolved_count, total_checked)
        """
        # Get existing review comments
        comments = self.get_existing_review_comments()

        if not comments:
            return 0, 0

        # Filter for our bot's comments
        bot_comments = [
            c for c in comments
            if c.get("user", {}).get("login") == "github-actions[bot]"
        ]

        resolved = 0
        total = len(bot_comments)

        for comment in bot_comments:
            file = comment.get("path", "")
            line = comment.get("line", 0)
            comment_id = comment.get("id")

            if self._is_line_fixed(file, line, current_diff):
                if self.resolve_comment(comment_id):
                    resolved += 1

        return resolved, total
