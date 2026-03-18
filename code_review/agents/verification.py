"""Verification agent for filtering false positives."""

from .base import BaseAgent, AgentContext, Finding


class VerificationAgent(BaseAgent):
    """Agent that verifies findings from other agents to filter false positives."""

    name = "verification"
    description = "Verifies findings from other agents and filters false positives"

    def _default_prompt(self) -> str:
        return """You are a verification agent that cross-checks code review findings.

Your job is to verify whether reported issues are genuine problems or false positives.

## Verification Criteria

1. **Code Accuracy**
   - Does the issue exist at the reported line?
   - Is the file path correct?
   - Is the code as described?

2. **Issue Validity**
   - Is this actually a problem?
   - Could this cause real issues?
   - Is the severity appropriate?

3. **Context Consideration**
   - Is there context that invalidates the issue?
   - Are there tests that cover this?
   - Is this intentional behavior?

4. **False Positive Patterns**
   - Feature flags or conditional code
   - Test-only code
   - Intentional patterns
   - Already handled elsewhere

## Findings to Verify

{{FINDINGS}}

## Full Code Context

{{FILES}}

## Additional Context

{{CONTEXT}}

## Instructions

For each finding, determine if it's:
- VALID: A real issue that should be reported
- INVALID: A false positive that should be filtered

Respond with:

VERIFY: <file>:<line>
STATUS: VALID|INVALID
CONFIDENCE: 0.0-1.0
REASONING: <explanation>
---

Be strict. Only mark as VALID if you're confident it's a real issue.
"""

    def build_verification_prompt(
        self,
        findings: list[Finding],
        context: AgentContext,
    ) -> str:
        """Build prompt for verifying findings."""
        findings_text = ""
        for i, f in enumerate(findings, 1):
            findings_text += f"""
### Finding {i}
- File: {f.file}
- Line: {f.line}
- Severity: {f.severity}
- Message: {f.message}
- Agent: {f.agent}
- Original Reasoning: {f.reasoning}
---
"""

        prompt = self.prompt_template.replace("{{FINDINGS}}", findings_text)

        files_section = ""
        for path, content in context.file_contents.items():
            files_section += f"\n### File: {path}\n```\n{content}\n```\n"
        prompt = prompt.replace("{{FILES}}", files_section)

        context_section = ""
        for path, content in context.context_files.items():
            context_section += f"\n### Context: {path}\n```\n{content}\n```\n"
        prompt = prompt.replace("{{CONTEXT}}", context_section)

        return prompt

    def parse_verification_response(
        self,
        response: str,
        original_findings: list[Finding],
    ) -> list[Finding]:
        """Parse verification response and return verified findings."""
        verified = []
        verification_results = {}

        current = {}
        for line in response.split("\n"):
            line = line.strip()

            if line.startswith("VERIFY:"):
                if current and "file" in current:
                    verification_results[
                        (current["file"], current.get("line", 0))
                    ] = current
                parts = line[7:].strip().split(":")
                current = {
                    "file": parts[0].strip() if parts else "",
                    "line": int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0,
                }
            elif line.startswith("STATUS:"):
                current["status"] = line[7:].strip().upper()
            elif line.startswith("CONFIDENCE:"):
                try:
                    current["confidence"] = float(line[11:].strip())
                except ValueError:
                    current["confidence"] = 0.5
            elif line.startswith("REASONING:"):
                current["reasoning"] = line[10:].strip()

        if current and "file" in current:
            verification_results[(current["file"], current.get("line", 0))] = current

        # Apply verification results to original findings
        for finding in original_findings:
            key = (finding.file, finding.line)
            result = verification_results.get(key, {})

            if result.get("status") == "VALID":
                finding.confidence = result.get("confidence", 0.5)
                if result.get("reasoning"):
                    finding.reasoning = f"Verified: {result['reasoning']}"
                verified.append(finding)
            elif result.get("status") != "INVALID":
                # If not explicitly invalid, include with reduced confidence
                finding.confidence = result.get("confidence", 0.5)
                verified.append(finding)

        return verified

    def verify(
        self,
        findings: list[Finding],
        context: AgentContext,
        confidence_threshold: float = 0.7,
    ) -> list[Finding]:
        """Verify findings and filter false positives."""
        if not findings:
            return []

        prompt = self.build_verification_prompt(findings, context)
        response = self.call_api(prompt)
        verified = self.parse_verification_response(response, findings)

        # Filter by confidence threshold
        return [f for f in verified if f.confidence >= confidence_threshold]

    def analyze(self, context: AgentContext) -> list[Finding]:
        """Not used for verification agent - use verify() instead."""
        return []
