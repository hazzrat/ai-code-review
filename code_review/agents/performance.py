"""Performance review agent."""

from .base import BaseAgent, AgentContext, Finding


class PerformanceAgent(BaseAgent):
    """Agent focused on performance issues and optimizations."""

    name = "performance"
    description = "Detects performance bottlenecks, inefficient code, and optimization opportunities"

    def _default_prompt(self) -> str:
        return """You are a performance engineer reviewing code for efficiency issues.

## Analysis Areas

### 1. Algorithmic Complexity
- Are there O(n²) or worse algorithms that could be optimized?
- Are there unnecessary nested loops?
- Is the data structure appropriate for the use case?

### 2. Memory Usage
- Are there memory leaks (event listeners not cleaned up)?
- Are large objects being unnecessarily copied?
- Are there inefficient data structures?

### 3. I/O Operations
- Are there N+1 query problems?
- Are database queries optimized?
- Are there unnecessary API calls?
- Is there proper caching?

### 4. Async/Concurrency
- Are async operations handled efficiently?
- Are there blocking operations that could be non-blocking?
- Are promises/async-await used correctly?

### 5. Frontend Performance (React)
- Are there unnecessary re-renders?
- Is memo/useMemo/useCallback used appropriately?
- Are large lists virtualized?
- Are images optimized?

### 6. Bundle Size
- Are there large imports that could be code-split?
- Are there unused dependencies?

## Output Format

FINDING: <file_path>:<line_number>
SEVERITY: bug|nit|pre-existing
MESSAGE: <description of the performance issue>
REASONING: <why this affects performance>
SUGGESTION: <optimization recommendation>
---

Severity Guide:
- bug: Critical performance issue causing user-visible problems
- nit: Optimization opportunity
"""

    def analyze(self, context: AgentContext) -> list[Finding]:
        return self.run(context)
