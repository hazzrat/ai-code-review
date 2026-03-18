"""PR and diff fetching module using gh CLI."""

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


@dataclass
class DiffHunk:
    """A single hunk in a diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    changes: list[tuple[str, int, str]] = field(default_factory=list)
    # Each change is (type, line_number, content)
    # type: '+' for addition, '-' for deletion, ' ' for context


@dataclass
class FileDiff:
    """Diff for a single file."""
    old_path: str
    new_path: str
    status: str  # added, modified, deleted, renamed
    hunks: list[DiffHunk] = field(default_factory=list)

    @property
    def is_new_file(self) -> bool:
        return self.status == "added"

    @property
    def is_deleted(self) -> bool:
        return self.status == "deleted"


@dataclass
class PRInfo:
    """Pull request information."""
    number: int
    title: str
    body: str
    author: str
    base_branch: str
    head_branch: str
    url: str
    files: list[str] = field(default_factory=list)


@dataclass
class FetchedPR:
    """Fetched PR data with all necessary information."""
    info: PRInfo
    diffs: list[FileDiff]
    file_contents: dict[str, str] = field(default_factory=dict)
    context_files: dict[str, str] = field(default_factory=dict)


def run_gh_command(args: list[str], check: bool = True) -> str:
    """Run a gh CLI command and return output."""
    cmd = ["gh"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"gh command failed: {result.stderr}")
    return result.stdout


def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Parse PR URL into (owner, repo, pr_number).

    Handles formats:
    - https://github.com/owner/repo/pull/123
    - owner/repo#123
    """
    if url.startswith("http"):
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 4 and parts[2] == "pull":
            return parts[0], parts[1], int(parts[3])
    elif "#" in url:
        repo, num = url.split("#")
        owner, repo_name = repo.split("/")
        return owner, repo_name, int(num)

    raise ValueError(f"Invalid PR URL format: {url}")


def fetch_pr_info(owner: str, repo: str, pr_number: int) -> PRInfo:
    """Fetch PR metadata using gh CLI."""
    result = run_gh_command([
        "pr", "view", str(pr_number),
        "--repo", f"{owner}/{repo}",
        "--json", "number,title,body,author,baseRefName,headRefName,url,files"
    ])

    try:
        data = json.loads(result)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse PR info JSON: {e}")

    # Safely extract author login
    author_data = data.get("author")
    author_login = "unknown"
    if isinstance(author_data, dict):
        author_login = author_data.get("login", "unknown")

    return PRInfo(
        number=data.get("number", pr_number),
        title=data.get("title", ""),
        body=data.get("body", ""),
        author=author_login,
        base_branch=data.get("baseRefName", "main"),
        head_branch=data.get("headRefName", ""),
        url=data.get("url", ""),
        files=[f.get("path", "") for f in data.get("files", [])],
    )


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Parse unified diff format into structured FileDiff objects."""
    diffs = []
    current_diff = None
    current_hunk = None

    for line in diff_text.split("\n"):
        # New file diff header
        if line.startswith("diff --git "):
            if current_diff:
                if current_hunk:
                    current_diff.hunks.append(current_hunk)
                diffs.append(current_diff)

            parts = line.split(" ")
            # Format: diff --git a/path b/path
            old_path = parts[2][2:] if parts[2].startswith("a/") else parts[2]
            new_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
            current_diff = FileDiff(
                old_path=old_path,
                new_path=new_path,
                status="modified",
                hunks=[]
            )
            current_hunk = None
            continue

        if current_diff is None:
            continue

        # File status indicators
        if line.startswith("new file mode"):
            current_diff.status = "added"
        elif line.startswith("deleted file mode"):
            current_diff.status = "deleted"
        elif line.startswith("rename from "):
            current_diff.status = "renamed"
            current_diff.old_path = line[12:]

        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        if line.startswith("@@"):
            if current_hunk:
                current_diff.hunks.append(current_hunk)

            # Parse hunk header
            import re
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                current_hunk = DiffHunk(
                    old_start=int(match.group(1)),
                    old_count=int(match.group(2) or 1),
                    new_start=int(match.group(3)),
                    new_count=int(match.group(4) or 1),
                    content=line,
                    changes=[]
                )
            continue

        # Diff content
        if current_hunk:
            if line.startswith("+"):
                current_hunk.changes.append(
                    ("+", current_hunk.new_start + len([
                        c for c in current_hunk.changes if c[0] in ("+", " ")
                    ]), line[1:])
                )
            elif line.startswith("-"):
                current_hunk.changes.append(
                    ("-", current_hunk.old_start + len([
                        c for c in current_hunk.changes if c[0] in ("-", " ")
                    ]), line[1:])
                )
            elif line.startswith(" ") or line == "":
                current_hunk.changes.append(
                    (" ", current_hunk.new_start + len([
                        c for c in current_hunk.changes if c[0] in ("+", " ")
                    ]), line[1:] if line else "")
                )

    # Don't forget the last diff
    if current_diff:
        if current_hunk:
            current_diff.hunks.append(current_hunk)
        diffs.append(current_diff)

    return diffs


def fetch_diff(owner: str, repo: str, pr_number: int) -> list[FileDiff]:
    """Fetch and parse PR diff."""
    result = run_gh_command([
        "pr", "diff", str(pr_number),
        "--repo", f"{owner}/{repo}",
    ])

    return parse_diff(result)


def fetch_file_content(
    owner: str,
    repo: str,
    path: str,
    ref: str = "HEAD"
) -> Optional[str]:
    """Fetch content of a file at a specific ref."""
    try:
        result = run_gh_command([
            "api",
            f"repos/{owner}/{repo}/contents/{path}",
            "--jq", ".content",
        ], check=False)

        if not result.strip():
            return None

        import base64
        return base64.b64decode(result.strip()).decode("utf-8")
    except Exception:
        return None


def fetch_changed_files(
    owner: str,
    repo: str,
    pr_number: int,
    diffs: list[FileDiff],
) -> dict[str, str]:
    """Fetch content of all changed files."""
    contents = {}

    for diff in diffs:
        if not diff.is_deleted:
            content = fetch_file_content(owner, repo, diff.new_path)
            if content:
                contents[diff.new_path] = content

    return contents


def identify_context_files(
    diffs: list[FileDiff],
    file_contents: dict[str, str],
) -> list[str]:
    """Identify related files that provide context (imports, tests, etc.)."""
    context_candidates = set()

    for diff in diffs:
        path = diff.new_path

        # Look for test files
        if not path.startswith("test") and not path.endswith("_test.py"):
            test_candidates = [
                f"test_{path}",
                path.replace(".py", "_test.py"),
                path.replace("src/", "tests/"),
                path.replace("lib/", "test/"),
            ]
            for tc in test_candidates:
                context_candidates.add(tc)

        # Extract imports from file content
        if path in file_contents:
            content = file_contents[path]
            for line in content.split("\n"):
                if line.startswith("import ") or line.startswith("from "):
                    # Extract module path
                    parts = line.split()
                    if len(parts) >= 2:
                        module = parts[1].split(".")[0]
                        context_candidates.add(f"{module}.py")
                        context_candidates.add(f"src/{module}.py")
                        context_candidates.add(f"lib/{module}.py")

    return list(context_candidates)


def fetch_context_files(
    owner: str,
    repo: str,
    context_paths: list[str],
    existing_contents: dict[str, str],
) -> dict[str, str]:
    """Fetch context files that aren't already in existing_contents."""
    context_contents = {}

    for path in context_paths:
        if path not in existing_contents:
            content = fetch_file_content(owner, repo, path)
            if content:
                context_contents[path] = content

    return context_contents


def fetch_pr(
    pr_url: str,
    include_context: bool = True,
) -> FetchedPR:
    """Main entry point: fetch all PR data needed for review.

    Args:
        pr_url: PR URL or shorthand (owner/repo#123)
        include_context: Whether to fetch related context files

    Returns:
        FetchedPR with all necessary data
    """
    owner, repo, pr_number = parse_pr_url(pr_url)

    # Fetch PR info and diff in parallel conceptually
    info = fetch_pr_info(owner, repo, pr_number)
    diffs = fetch_diff(owner, repo, pr_number)

    # Fetch file contents
    file_contents = fetch_changed_files(owner, repo, pr_number, diffs)

    # Fetch context files
    context_files = {}
    if include_context:
        context_paths = identify_context_files(diffs, file_contents)
        context_files = fetch_context_files(owner, repo, context_paths, file_contents)

    return FetchedPR(
        info=info,
        diffs=diffs,
        file_contents=file_contents,
        context_files=context_files,
    )


def fetch_local_diff(base: str = "main", repo_path: str = ".") -> list[FileDiff]:
    """Fetch diff from local git repository.

    Args:
        base: Base branch to compare against
        repo_path: Path to the git repository

    Returns:
        List of FileDiff objects
    """
    import os
    original_dir = os.getcwd()

    try:
        if repo_path != ".":
            os.chdir(repo_path)

        result = subprocess.run(
            ["git", "diff", base + "...HEAD"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"git diff failed: {result.stderr}")

        return parse_diff(result.stdout)
    finally:
        os.chdir(original_dir)


def fetch_local_files(diffs: list[FileDiff]) -> dict[str, str]:
    """Fetch content of locally changed files."""
    contents = {}

    for diff in diffs:
        path = Path(diff.new_path)
        if path.exists() and diff.status != "deleted":
            try:
                contents[diff.new_path] = path.read_text()
            except Exception:
                pass

    return contents
