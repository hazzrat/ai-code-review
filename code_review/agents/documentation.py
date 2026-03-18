"""Documentation review agent."""

from .base import BaseAgent, AgentContext, Finding


class DocumentationAgent(BaseAgent):
    """Agent focused on documentation quality and completeness."""

    name = "documentation"
    description = "Detects missing documentation, outdated comments, and docstring issues"

    def _default_prompt(self) -> str:
        return """You are a technical writer reviewing code documentation.

## Analysis Areas

### 1. Missing Documentation
- Are public functions/methods documented?
- Are complex algorithms explained?
- Are API endpoints documented?
- Are there README files for modules?

### 2. Outdated Documentation
- Do comments match the code?
- Are TODO/FIXME items still relevant?
- Are deprecated functions marked?

### 3. Documentation Quality
- Are docstrings complete (params, returns, examples)?
- Is the language clear and concise?
- Are there code examples where helpful?

### 4. Inline Comments
- Is complex logic explained?
- Are magic numbers documented?
- Are workarounds explained?

## Output Format

FINDING: <file_path>:<line_number>
SEVERITY: bug|nit|pre-existing
MESSAGE: <documentation issue>
REASONING: <why this documentation is important>
SUGGESTION: <suggested documentation text>
---

Severity Guide:
- bug: Missing critical documentation that will cause problems
- nit: Documentation improvement suggestion
"""

    def analyze(self, context: AgentContext) -> list[Finding]:
        return self.run(context)
