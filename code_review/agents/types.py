"""Type safety detection agent."""

from .base import BaseAgent, AgentContext, Finding


class TypesAgent(BaseAgent):
    """Agent focused on type correctness and type safety."""

    name = "types"
    description = "Detects type errors, mismatches, and type safety issues"

    def _default_prompt(self) -> str:
        return """You are a type safety focused code reviewer.

Analyze the following diff and code for type-related issues:

## Type Errors

1. **Type Mismatches**
   - Passing wrong type to function
   - Assigning incompatible types
   - Returning wrong type
   - Comparing incompatible types

2. **Missing Type Handling**
   - Optional values treated as required
   - Union types not fully handled
   - Null/undefined not accounted for

3. **Type Coercion Issues**
   - Implicit coercions (JavaScript)
   - Loss of precision
   - Unexpected type conversions

## Common Type Patterns

1. **Collections**
   - Mixed type arrays
   - Incorrect key types
   - Missing generic parameters

2. **Function Types**
   - Incorrect parameter types
   - Return type mismatches
   - Callback signature errors

3. **Object Types**
   - Missing required properties
   - Extra properties
   - Incorrect property types

## Language-Specific Issues

1. **JavaScript/TypeScript**
   - any type overuse
   - Type assertion safety
   - Nullish coalescing vs OR

2. **Python**
   - Missing type hints
   - Dynamic type issues
   - None handling

3. **Go**
   - Interface satisfaction
   - Nil pointer dereference
   - Type assertion safety

## Diff

{{DIFF}}

## Changed Files

{{FILES}}

## Context Files

{{CONTEXT}}

{{RULES}}

## Instructions

For each type issue found:

FINDING: <file_path>:<line_number>
SEVERITY: bug|nit|pre-existing
MESSAGE: <description of the type issue>
REASONING: <why this is a type safety problem>
SUGGESTION: <how to fix the type issue>
---

Report issues that could cause runtime errors or incorrect behavior. Style preferences for type hints are nits.
"""

    def analyze(self, context: AgentContext) -> list[Finding]:
        return self.run(context)
