"""Configuration management for code review system."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class APIConfig:
    """API configuration settings."""
    endpoint: str = "https://api.z.ai/api/anthropic"
    model: str = "glm-5"
    max_tokens: int = 4096
    timeout: int = 120


@dataclass
class AgentConfig:
    """Individual agent configuration."""
    name: str
    enabled: bool = True
    priority: int = 1


@dataclass
class ReviewConfig:
    """Review process configuration."""
    min_agents: int = 3
    max_agents: int = 6
    severity_threshold: str = "nit"
    max_diff_size: int = 100000


@dataclass
class VerificationConfig:
    """Verification agent configuration."""
    enabled: bool = True
    confidence_threshold: float = 0.7


@dataclass
class OutputConfig:
    """Output configuration."""
    post_comments: bool = True
    verbose: bool = False
    format: str = "github"


@dataclass
class CLAUDEmdConfig:
    """CLAUDE.md configuration for bidirectional checking."""
    content: str = ""
    rules: list[str] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)
    path: Optional[Path] = None


@dataclass
class Config:
    """Main configuration container."""
    api: APIConfig = field(default_factory=APIConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    agents: list[AgentConfig] = field(default_factory=list)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    review_rules: list[str] = field(default_factory=list)
    claude_md: CLAUDEmdConfig = field(default_factory=CLAUDEmdConfig)
    claude_md_files: list[Path] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        config = cls()

        if "api" in data:
            config.api = APIConfig(**data["api"])
        if "review" in data:
            config.review = ReviewConfig(**data["review"])
        if "agents" in data:
            config.agents = [AgentConfig(**a) for a in data["agents"]]
        if "verification" in data:
            config.verification = VerificationConfig(**data["verification"])
        if "output" in data:
            config.output = OutputConfig(**data["output"])

        return config

    def get_enabled_agents(self) -> list[str]:
        """Get list of enabled agent names."""
        return [a.name for a in self.agents if a.enabled]


def parse_review_md(path: Path) -> list[str]:
    """Parse REVIEW.md for review rules.

    Looks for sections like:
    ## Code Review Guidelines
    - Rule 1
    - Rule 2
    """
    rules = []

    if not path.exists():
        return rules

    with open(path) as f:
        content = f.read()

    # Look for code review sections
    in_review_section = False
    for line in content.split("\n"):
        if line.startswith("## Code Review") or line.startswith("## Review"):
            in_review_section = True
            continue
        if line.startswith("##") and in_review_section:
            in_review_section = False
        if in_review_section and line.strip().startswith("-"):
            rules.append(line.strip().lstrip("- ").strip())

    return rules


def parse_claude_md(path: Path) -> CLAUDEmdConfig:
    """Parse CLAUDE.md for full bidirectional support.

    Extracts:
    - All rules as a flat list
    - Sections with their associated rules
    - Full content for context

    The official Claude Code Review treats CLAUDE.md bidirectionally:
    1. New code violations are flagged as nit-level findings
    2. Changes that make CLAUDE.md statements outdated are also flagged
    """
    config = CLAUDEmdConfig()

    if not path.exists():
        return config

    with open(path) as f:
        config.content = f.read()
        config.path = path

    current_section = "general"
    config.sections = {"general": []}

    for line in config.content.split("\n"):
        # Detect section headers
        if line.startswith("## "):
            current_section = line[3:].strip()
            config.sections[current_section] = []
            continue

        # Extract list items as rules
        if line.strip().startswith("-") or line.strip().startswith("*"):
            rule = line.strip().lstrip("-* ").strip()
            config.rules.append(rule)
            if current_section in config.sections:
                config.sections[current_section].append(rule)

    return config


def discover_claude_md_files(repo_path: Path) -> list[Path]:
    """Discover all CLAUDE.md files in a repository hierarchy.

    Claude reads CLAUDE.md files at every level of the directory hierarchy,
    so rules in a subdirectory's CLAUDE.md apply only to files under that path.
    """
    claude_files = []

    # Check root level first
    root_claude = repo_path / "CLAUDE.md"
    if root_claude.exists():
        claude_files.append(root_claude)

    # Search subdirectories
    for claude_file in repo_path.rglob("CLAUDE.md"):
        if claude_file not in claude_files:
            claude_files.append(claude_file)

    return sorted(claude_files)


def load_config(
    config_path: Optional[Path] = None,
    review_md_path: Optional[Path] = None,
    claude_md_path: Optional[Path] = None,
    repo_path: Optional[Path] = None,
) -> Config:
    """Load configuration from files and environment.

    Priority:
    1. Environment variables (highest)
    2. Specified config file
    3. Default config.yaml
    4. Defaults
    """
    # Start with default config
    config = Config()

    # Try to load from default locations
    default_config_paths = [
        Path("config.yaml"),
        Path.home() / ".config" / "code-review" / "config.yaml",
        Path(__file__).parent.parent / "config.yaml",
    ]

    # Load from file
    config_file = config_path
    if config_file is None:
        for p in default_config_paths:
            if p.exists():
                config_file = p
                break

    if config_file and config_file.exists():
        config = Config.from_yaml(config_file)

    # Override with environment variables
    if os.environ.get("CODE_REVIEW_API_ENDPOINT"):
        endpoint = os.environ["CODE_REVIEW_API_ENDPOINT"]
        # Validate URL format
        if endpoint.startswith(("http://", "https://")):
            config.api.endpoint = endpoint
        else:
            print(f"Warning: Invalid API endpoint URL format: {endpoint}")
    if os.environ.get("CODE_REVIEW_API_KEY"):
        # Store in api config for use
        config.api.model = os.environ.get("CODE_REVIEW_API_MODEL", config.api.model)

    # Load review rules from REVIEW.md
    review_paths = [
        review_md_path,
        Path("REVIEW.md"),
    ]
    for rp in review_paths:
        if rp and rp.exists():
            config.review_rules = parse_review_md(rp)
            break

    # Load CLAUDE.md for bidirectional checking
    if claude_md_path and claude_md_path.exists():
        config.claude_md = parse_claude_md(claude_md_path)
        config.claude_md_files = [claude_md_path]
    elif repo_path:
        # Discover all CLAUDE.md files in repo hierarchy
        config.claude_md_files = discover_claude_md_files(repo_path)
        # Load root CLAUDE.md
        root_claude = repo_path / "CLAUDE.md"
        if root_claude.exists():
            config.claude_md = parse_claude_md(root_claude)
    else:
        # Check for local CLAUDE.md
        local_claude = Path("CLAUDE.md")
        if local_claude.exists():
            config.claude_md = parse_claude_md(local_claude)
            config.claude_md_files = [local_claude]

    # Merge CLAUDE.md rules into review_rules
    if config.claude_md.rules:
        config.review_rules = config.review_rules + config.claude_md.rules

    return config
