"""GitHub comment posting module."""

import json
import subprocess
from typing import Optional

from .agents.base import Finding
from .fetcher import FetchedPR


class CommentPoster:
    """Posts review comments to GitHub PRs."""

    def __init__(self, pr_url: str):
        self.pr_url = pr_url
        self.owner, self.repo, self.pr_number = self._parse_url(pr_url)

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

    def post_overview_comment(self, body: str) -> None:
        """Post an overview comment on the PR."""
        # Use a temp file for the body to avoid shell escaping issues
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(body)
            temp_path = f.name

        try:
            self._run_gh([
                "pr", "comment", str(self.pr_number),
                "--repo", f"{self.owner}/{self.repo}",
                "--body-file", temp_path,
            ])
        finally:
            import os
            os.unlink(temp_path)

    def post_inline_comment(
        self,
        file: str,
        line: int,
        body: str,
    ) -> None:
        """Post an inline comment on a specific line using JSON input."""
        import tempfile

        # Get the latest commit SHA
        result = self._run_gh([
            "pr", "view", str(self.pr_number),
            "--repo", f"{self.owner}/{self.repo}",
            "--json", "headRefOid",
        ])
        data = json.loads(result)
        commit_sha = data["headRefOid"]

        # Create JSON payload with proper types
        payload = {
            "body": body,
            "commit_id": commit_sha,
            "path": file,
            "line": int(line),  # Ensure integer type
            "side": "RIGHT",
        }

        # Write to temp file for JSON input
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(payload, f)
            temp_path = f.name

        try:
            self._run_gh([
                "api",
                "--method", "POST",
                f"repos/{self.owner}/{self.repo}/pulls/{self.pr_number}/comments",
                "--input", temp_path,
            ])
        finally:
            import os
            os.unlink(temp_path)

    def format_finding_comment(self, finding: Finding) -> str:
        """Format a finding as a GitHub comment."""
        severity_emoji = {
            "bug": "🔴",
            "nit": "🟡",
            "pre-existing": "🟣",
        }

        emoji = severity_emoji.get(finding.severity, "⚪")
        severity_label = finding.severity.upper()

        lines = [
            f"### {emoji} {severity_label}",
            "",
            finding.message,
        ]

        if finding.suggestion:
            lines.extend([
                "",
                "**Suggestion:**",
                "```suggestion",
                finding.suggestion,
                "```",
            ])

        if finding.reasoning:
            lines.extend([
                "",
                "<details>",
                "<summary>Reasoning</summary>",
                "",
                finding.reasoning,
                "</details>",
            ])

        return "\n".join(lines)

    def post_findings(
        self,
        findings: list[Finding],
        pr_data: Optional[FetchedPR] = None,
        max_inline_comments: int = 10,
    ) -> None:
        """Post all findings as comments.

        Posts:
        1. Overview comment with summary
        2. Inline comments for specific issues (up to max_inline_comments)
        """
        if not findings:
            self.post_overview_comment(
                "## Code Review ✅\n\n"
                "No issues found in this PR. Great work!"
            )
            return

        # Generate and post overview
        overview = self._generate_overview(findings)
        self.post_overview_comment(overview)

        # Post inline comments for bugs first, then nits
        bugs = [f for f in findings if f.severity == "bug"]
        nits = [f for f in findings if f.severity == "nit"]

        inline_findings = (bugs + nits)[:max_inline_comments]

        for finding in inline_findings:
            if finding.line > 0:  # Only post if we have a valid line
                try:
                    comment = self.format_finding_comment(finding)
                    self.post_inline_comment(
                        finding.file,
                        finding.line,
                        comment,
                    )
                except Exception as e:
                    # If inline comment fails, we've already posted overview
                    print(f"Warning: Failed to post inline comment: {e}")

    def _generate_overview(self, findings: list[Finding]) -> str:
        """Generate overview comment body."""
        bugs = [f for f in findings if f.severity == "bug"]
        nits = [f for f in findings if f.severity == "nit"]
        preexisting = [f for f in findings if f.severity == "pre-existing"]

        lines = [
            "## Code Review Summary",
            "",
            f"🤖 **Automated review using {len(findings)} specialized agents**",
            "",
        ]

        if bugs:
            lines.extend([
                f"### 🔴 Bugs ({len(bugs)})",
                "",
                "The following issues require attention:",
                "",
            ])
            for f in bugs:
                lines.append(f"- **{f.file}:{f.line}** - {f.message}")
            lines.append("")

        if nits:
            lines.extend([
                f"### 🟡 Suggestions ({len(nits)})",
                "",
                "Consider addressing these suggestions:",
                "",
            ])
            for f in nits[:10]:  # Limit in overview
                lines.append(f"- **{f.file}:{f.line}** - {f.message}")
            if len(nits) > 10:
                lines.append(f"- ... and {len(nits) - 10} more")
            lines.append("")

        if preexisting:
            lines.extend([
                f"### 🟣 Pre-existing Issues ({len(preexisting)})",
                "",
                "Some issues found appear to pre-exist in the codebase:",
                "",
            ])
            for f in preexisting[:5]:
                lines.append(f"- **{f.file}:{f.line}** - {f.message}")
            lines.append("")

        lines.extend([
            "---",
            "",
            "<details>",
            "<summary>Review Details</summary>",
            "",
            f"- **Agents used:** logic, security, edge_cases, types, regression",
            f"- **Total findings:** {len(findings)}",
            f"- **Bugs:** {len(bugs)} | **Nits:** {len(nits)} | **Pre-existing:** {len(preexisting)}",
            "",
            "</details>",
        ])

        return "\n".join(lines)


def format_findings_for_local(findings: list[Finding]) -> str:
    """Format findings for local display (no GitHub)."""
    if not findings:
        return "✅ No issues found."

    bugs = [f for f in findings if f.severity == "bug"]
    nits = [f for f in findings if f.severity == "nit"]
    preexisting = [f for f in findings if f.severity == "pre-existing"]

    lines = []

    if bugs:
        lines.append(f"\n🔴 Bugs ({len(bugs)})")
        lines.append("-" * 40)
        for f in bugs:
            lines.append(f"  {f.file}:{f.line}")
            lines.append(f"    {f.message}")
            if f.suggestion:
                lines.append(f"    Suggestion: {f.suggestion}")

    if nits:
        lines.append(f"\n🟡 Nits ({len(nits)})")
        lines.append("-" * 40)
        for f in nits:
            lines.append(f"  {f.file}:{f.line}")
            lines.append(f"    {f.message}")

    if preexisting:
        lines.append(f"\n🟣 Pre-existing ({len(preexisting)})")
        lines.append("-" * 40)
        for f in preexisting:
            lines.append(f"  {f.file}:{f.line}")
            lines.append(f"    {f.message}")

    return "\n".join(lines)
