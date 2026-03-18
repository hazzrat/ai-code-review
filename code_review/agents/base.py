"""Base agent class for code review agents."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import Config


class Severity(Enum):
    """Finding severity levels."""
    BUG = "bug"
    NIT = "nit"
    PRE_EXISTING = "pre-existing"


@dataclass
class Finding:
    """A code review finding."""
    file: str
    line: int
    message: str
    severity: str  # bug, nit, pre-existing
    reasoning: str = ""
    agent: str = ""
    confidence: float = 1.0
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "severity": self.severity,
            "reasoning": self.reasoning,
            "agent": self.agent,
            "confidence": self.confidence,
            "suggestion": self.suggestion,
        }


@dataclass
class AgentContext:
    """Context provided to agents for analysis."""
    diff_text: str
    file_contents: dict[str, str]
    context_files: dict[str, str]
    review_rules: list[str] = field(default_factory=list)
    pr_title: str = ""
    pr_body: str = ""
    claude_md: str = ""  # Full CLAUDE.md content for bidirectional checking


class BaseAgent(ABC):
    """Abstract base class for code review agents."""

    name: str = "base"
    description: str = "Base agent"

    def __init__(self, config: Config):
        self.config = config
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the agent's prompt template from file."""
        prompt_path = (
            Path(__file__).parent.parent.parent
            / "prompts" / f"{self.name}.txt"
        )
        if prompt_path.exists():
            return prompt_path.read_text()
        return self._default_prompt()

    @abstractmethod
    def _default_prompt(self) -> str:
        """Return default prompt if template file not found."""
        pass

    def build_prompt(self, context: AgentContext) -> str:
        """Build the full prompt for the agent."""
        prompt = self.prompt_template

        # Add diff content
        prompt = prompt.replace("{{DIFF}}", context.diff_text)

        # Add file contents
        files_section = ""
        for path, content in context.file_contents.items():
            files_section += f"\n### File: {path}\n```\n{content}\n```\n"
        prompt = prompt.replace("{{FILES}}", files_section)

        # Add context files
        context_section = ""
        for path, content in context.context_files.items():
            context_section += f"\n### Context: {path}\n```\n{content}\n```\n"
        prompt = prompt.replace("{{CONTEXT}}", context_section)

        # Add review rules
        rules_section = ""
        if context.review_rules:
            rules_section = "Custom Review Rules:\n" + "\n".join(
                f"- {rule}" for rule in context.review_rules
            )
        prompt = prompt.replace("{{RULES}}", rules_section)

        return prompt

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
    )
    def call_api(self, prompt: str) -> str:
        """Call the GLM-5 API with the prompt."""
        import os

        endpoint = self.config.api.endpoint
        model = self.config.api.model
        max_tokens = self.config.api.max_tokens

        # API key from environment - check multiple possible variable names
        api_key = (
            os.environ.get("CODE_REVIEW_API_KEY") or
            os.environ.get("ANTHROPIC_API_KEY") or
            os.environ.get("CLAUDE_API_KEY") or
            ""
        )

        if not api_key:
            raise ValueError(
                "No API key found. Please set one of these environment variables:\n"
                "  - CODE_REVIEW_API_KEY\n"
                "  - ANTHROPIC_API_KEY\n"
                "  - CLAUDE_API_KEY\n\n"
                "Example: export CODE_REVIEW_API_KEY=your-api-key"
            )

        # Build endpoint URL - append /v1/messages if needed
        api_url = endpoint
        if not api_url.endswith("/v1/messages"):
            api_url = endpoint.rstrip("/") + "/v1/messages"

        # Build request based on API format (Anthropic-compatible)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            # Deterministic settings
            "temperature": self.config.api.temperature,
        }

        # Add seed for reproducibility if set
        if self.config.api.seed is not None:
            payload["seed"] = self.config.api.seed

        response = requests.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=self.config.api.timeout,
        )
        response.raise_for_status()

        data = response.json()
        # Handle Anthropic-style response
        if "content" in data:
            return data["content"][0]["text"]
        elif "choices" in data:
            return data["choices"][0]["message"]["content"]

        raise ValueError(f"Unexpected API response format: {data}")

    @abstractmethod
    def analyze(self, context: AgentContext) -> list[Finding]:
        """Analyze the code and return findings."""
        pass

    def parse_findings(self, response: str) -> list[Finding]:
        """Parse LLM response into structured findings.

        Expected format:
        FINDING: <file>:<line>
        SEVERITY: bug|nit|pre-existing
        MESSAGE: <description>
        REASONING: <explanation>
        SUGGESTION: <optional fix>
        ---
        """
        findings = []
        current = {}

        for line in response.split("\n"):
            line = line.strip()

            if line.startswith("FINDING:"):
                if current:
                    findings.append(self._create_finding(current))
                parts = line[8:].strip().split(":")
                current = {
                    "file": parts[0].strip() if len(parts) > 0 else "",
                    "line": int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0,
                }
            elif line.startswith("SEVERITY:"):
                current["severity"] = line[9:].strip().lower()
            elif line.startswith("MESSAGE:"):
                current["message"] = line[8:].strip()
            elif line.startswith("REASONING:"):
                current["reasoning"] = line[10:].strip()
            elif line.startswith("SUGGESTION:"):
                current["suggestion"] = line[11:].strip()
            elif line == "---":
                if current:
                    findings.append(self._create_finding(current))
                    current = {}

        # Don't forget the last finding
        if current:
            findings.append(self._create_finding(current))

        return [f for f in findings if f.file and f.message]

    def _create_finding(self, data: dict) -> Finding:
        """Create a Finding from parsed data."""
        return Finding(
            file=data.get("file", ""),
            line=data.get("line", 0),
            message=data.get("message", ""),
            severity=data.get("severity", "nit"),
            reasoning=data.get("reasoning", ""),
            suggestion=data.get("suggestion", ""),
            agent=self.name,
        )

    def run(self, context: AgentContext) -> list[Finding]:
        """Run the agent: build prompt, call API, parse response."""
        prompt = self.build_prompt(context)
        response = self.call_api(prompt)
        return self.parse_findings(response)
