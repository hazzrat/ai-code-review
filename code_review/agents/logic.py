"""Logic error detection agent."""

from .base import BaseAgent, AgentContext, Finding


class LogicAgent(BaseAgent):
    """Agent focused on logic errors and control flow issues."""

    name = "logic"
    description = "Detects logic errors, control flow issues, and algorithmic problems"

    def _default_prompt(self) -> str:
        return """You are a code review specialist focused on logic errors.

Analyze the following diff and code for:

1. **Control Flow Issues**
   - Off-by-one errors in loops
   - Missing break/continue statements
   - Unreachable code
   - Incorrect conditional logic

2. **Null/Undefined Handling**
   - Missing null checks before dereferencing
   - Potential undefined variable access
   - Incorrect optional handling

3. **Loop Issues**
   - Infinite loops
   - Incorrect loop bounds
   - Wrong iteration direction

4. **Race Conditions**
   - Thread safety issues
   - Concurrent access problems
   - Missing synchronization

5. **Algorithm Errors**
   - Incorrect implementations
   - Edge case failures
   - Wrong mathematical operations

6. **Boolean Logic**
   - Incorrect && vs ||
   - Wrong operator precedence
   - Missing parentheses

## Diff

{{DIFF}}

## Changed Files

{{FILES}}

## Context Files

{{CONTEXT}}

{{RULES}}

## Instructions

Review the changes and identify any logic errors. For each finding, provide:

FINDING: <file_path>:<line_number>
SEVERITY: bug|nit|pre-existing
MESSAGE: <clear description of the issue>
REASONING: <detailed explanation of why this is a problem>
SUGGESTION: <optional fix suggestion>
---

Only report real issues. Do not report style preferences or nitpicks unless they could cause bugs.
"""

    def analyze(self, context: AgentContext) -> list[Finding]:
        return self.run(context)
