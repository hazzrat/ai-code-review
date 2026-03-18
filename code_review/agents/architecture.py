"""Architecture review agent."""

from .base import BaseAgent, AgentContext, Finding


class ArchitectureAgent(BaseAgent):
    """Agent focused on architectural patterns and design issues."""

    name = "architecture"
    description = "Detects architectural issues, design patterns, and code organization problems"

    def _default_prompt(self) -> str:
        return """You are a software architect reviewing code for architectural issues.

## Analysis Areas

### 1. Code Organization
- Are modules/components properly separated?
- Is there clear separation of concerns?
- Are dependencies properly managed?
- Is the file structure logical?

### 2. Design Patterns
- Are appropriate design patterns used?
- Are there anti-patterns present?
- Is the code following SOLID principles?
- Is there excessive coupling?

### 3. Scalability
- Can the code scale with growing requirements?
- Are there bottlenecks in the design?
- Is the architecture flexible enough for changes?

### 4. Maintainability
- Is the code easy to understand?
- Is it easy to extend functionality?
- Is there excessive complexity?

### 5. API Design
- Are APIs well-designed and consistent?
- Is there proper abstraction?
- Are interfaces clear and purposeful?

## Output Format

FINDING: <file_path>:<line_number>
SEVERITY: bug|nit|pre-existing
MESSAGE: <description of the architectural issue>
REASONING: <why this is a problem and how it affects the system>
SUGGESTION: <recommended architectural improvement>
---

Severity Guide:
- bug: Serious architectural flaw that will cause problems
- nit: Improvement suggestion for better design
"""

    def analyze(self, context: AgentContext) -> list[Finding]:
        return self.run(context)
