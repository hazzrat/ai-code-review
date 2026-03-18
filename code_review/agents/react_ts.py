"""React and TypeScript specialist agent."""

from .base import BaseAgent, AgentContext, Finding


class ReactTSAgent(BaseAgent):
    """Agent focused on React and TypeScript best practices."""

    name = "react_ts"
    description = "Detects React hooks issues, TypeScript problems, and frontend anti-patterns"

    def _default_prompt(self) -> str:
        return """You are a React and TypeScript specialist focused on best practices.

Analyze the code for:

1. **React Hooks Issues**
   - Missing dependencies in useEffect
   - Stale closures
   - Incorrect hook usage

2. **TypeScript Issues**
   - any type usage
   - Missing type definitions
   - Incorrect type assertions

3. **State Management**
   - Race conditions in state updates
   - Unnecessary re-renders
   - Memory leaks

## Diff

{{DIFF}}

## Changed Files

{{FILES}}

## Context Files

{{CONTEXT}}

{{RULES}}

## Output Format

FINDING: <file_path>:<line_number>
SEVERITY: bug|nit|pre-existing
MESSAGE: <description>
REASONING: <explanation>
SUGGESTION: <fix>
---
"""

    def analyze(self, context: AgentContext) -> list[Finding]:
        return self.run(context)
