"""Agent for checking CLAUDE.md compliance and bidirectional violations."""

from .base import BaseAgent, AgentContext, Finding


class ClaudeMdAgent(BaseAgent):
    """Agent that checks for CLAUDE.md violations and outdated documentation.

    This implements the bidirectional checking described in Claude Code Review:
    1. Flags code changes that violate CLAUDE.md rules (nit-level)
    2. Flags code changes that make CLAUDE.md statements outdated
    """

    name = "claude_md"
    description = "Checks CLAUDE.md compliance and flags outdated documentation"

    def _default_prompt(self) -> str:
        return """You are a CLAUDE.md compliance checker.

Your job is to check if code changes violate the project's CLAUDE.md guidelines
or if changes make the CLAUDE.md documentation outdated.

## CLAUDE.md Content

{{CLAUDE_MD}}

## Code Changes

{{DIFF}}

## Full File Context

{{FILES}}

## Instructions

Check for two types of issues:

### 1. Code Violations (severity: nit)
Code that violates rules in CLAUDE.md. For example:
- If CLAUDE.md says "use snake_case for variables" and new code uses camelCase
- If CLAUDE.md says "always handle errors" and new code ignores errors
- If CLAUDE.md says "all API endpoints need auth" and a new endpoint lacks auth

### 2. Outdated Documentation (severity: nit)
Changes that make CLAUDE.md statements incorrect. For example:
- CLAUDE.md describes a function that was removed or renamed
- CLAUDE.md mentions a file path that was changed
- CLAUDE.md documents behavior that was modified

Respond with findings in this format:

FINDING: <file>:<line>
SEVERITY: nit
MESSAGE: <description of the violation or outdated documentation>
REASONING: <which CLAUDE.md rule is affected and how>
SUGGESTION: <optional fix>
---

Only report real issues. Be thoughtful about context and intent.
"""

    def build_prompt(self, context: AgentContext) -> str:
        """Build the prompt with CLAUDE.md content."""
        prompt = self.prompt_template

        # Add CLAUDE.md content
        claude_md_content = ""
        if hasattr(context, 'claude_md') and context.claude_md:
            claude_md_content = context.claude_md
        prompt = prompt.replace("{{CLAUDE_MD}}", claude_md_content)

        # Add diff content
        prompt = prompt.replace("{{DIFF}}", context.diff_text)

        # Add file contents
        files_section = ""
        for path, content in context.file_contents.items():
            files_section += f"\n### File: {path}\n```\n{content}\n```\n"
        prompt = prompt.replace("{{FILES}}", files_section)

        return prompt

    def analyze(self, context: AgentContext) -> list[Finding]:
        """Analyze for CLAUDE.md violations."""
        # Skip if no CLAUDE.md content
        if not hasattr(context, 'claude_md') or not context.claude_md:
            return []

        prompt = self.build_prompt(context)
        response = self.call_api(prompt)
        return self.parse_findings(response)
