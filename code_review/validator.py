"""Finding validator to filter false positives and validate findings.

This module adds a validation layer that checks if findings are actually
present in the code, helping to filter out hallucinations from non-deterministic APIs.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .agents.base import Finding


@dataclass
class ValidationResult:
    """Result of validating a finding."""
    finding: Finding
    is_valid: bool
    confidence: float
    reason: str


class FindingValidator:
    """Validates findings against actual code to filter false positives."""

    # Patterns that indicate high-confidence findings
    HIGH_CONFIDENCE_PATTERNS = [
        r"hardcoded.*(?:api.?key|secret|password|token)",
        r"sql.?injection",
        r"xss|cross.?site.?scripting",
        r"eval\s*\(",
        r"dangerouslySetInnerHTML",
        r"\.innerHTML\s*=",
        r"localStorage\.(setItem|getItem).*token",
        r"console\.(log|debug|info)\s*\(",
        r"debug\s*:\s*true",
        r"TODO|FIXME|HACK|XXX",
    ]

    # Patterns that often cause false positives
    FALSE_POSITIVE_PATTERNS = [
        r"might\s+cause",
        r"could\s+potentially",
        r"may\s+lead",
        r"consider\s+adding",
        r"should\s+consider",
        r"might\s+want",
        r"could\s+improve",
        r"optional\s+enhancement",
    ]

    def __init__(self, repo_path: Optional[Path] = None):
        self.repo_path = repo_path or Path.cwd()
        self._file_cache: dict[str, str] = {}

    def _get_file_content(self, file_path: str) -> Optional[str]:
        """Get file content with caching."""
        if file_path in self._file_cache:
            return self._file_cache[file_path]

        full_path = self.repo_path / file_path
        if not full_path.exists():
            return None

        try:
            content = full_path.read_text(encoding='utf-8', errors='ignore')
            self._file_cache[file_path] = content
            return content
        except Exception:
            return None

    def _get_line_content(self, file_path: str, line_num: int) -> Optional[str]:
        """Get content at a specific line."""
        content = self._get_file_content(file_path)
        if not content:
            return None

        lines = content.split('\n')
        if 1 <= line_num <= len(lines):
            return lines[line_num - 1]
        return None

    def _check_finding_in_code(self, finding: Finding) -> tuple[bool, float, str]:
        """Check if the finding's issue is actually present in the code."""
        # Get file content
        content = self._get_file_content(finding.file)
        if content is None:
            return False, 0.3, "File not found"

        # Get the specific line if line number is provided
        line_content = None
        if finding.line > 0:
            line_content = self._get_line_content(finding.file, finding.line)

        # Extract key terms from the finding message
        message_lower = finding.message.lower()

        # Check for high-confidence patterns in the code
        for pattern in self.HIGH_CONFIDENCE_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                # Verify the pattern exists in the code
                if re.search(pattern, content, re.IGNORECASE):
                    return True, 0.95, f"High-confidence pattern found: {pattern[:30]}"

        # Check for false positive indicators in the message
        for pattern in self.FALSE_POSITIVE_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return True, 0.4, "Low confidence - speculative finding"

        # Check if key terms from the message appear in the file
        key_terms = self._extract_key_terms(finding.message)
        if key_terms:
            found_terms = sum(1 for term in key_terms if term.lower() in content.lower())
            if found_terms >= len(key_terms) * 0.5:
                return True, 0.7, f"Key terms found in file: {found_terms}/{len(key_terms)}"

        # Check line-specific content
        if line_content:
            # Extract function/variable names from the finding
            identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', finding.message)
            code_identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', line_content)

            matching = set(identifiers) & set(code_identifiers)
            if matching:
                return True, 0.8, f"Identifiers found at line: {matching}"

        # Default: finding might be valid but needs verification
        return True, 0.5, "Unable to fully verify - needs manual review"

    def _extract_key_terms(self, message: str) -> list[str]:
        """Extract key technical terms from a finding message."""
        # Remove common words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                      'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                      'can', 'need', 'to', 'of', 'in', 'for', 'on', 'with', 'at',
                      'by', 'from', 'as', 'into', 'through', 'during', 'before',
                      'after', 'above', 'below', 'between', 'under', 'again',
                      'further', 'then', 'once', 'this', 'that', 'these', 'those'}

        words = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', message.lower())
        return [w for w in words if w not in stop_words and len(w) > 2]

    def validate_finding(self, finding: Finding) -> ValidationResult:
        """Validate a single finding against the code."""
        is_valid, confidence, reason = self._check_finding_in_code(finding)

        return ValidationResult(
            finding=finding,
            is_valid=is_valid,
            confidence=confidence,
            reason=reason,
        )

    def validate_findings(
        self,
        findings: list[Finding],
        min_confidence: float = 0.5,
    ) -> list[Finding]:
        """Validate and filter findings by confidence."""
        validated = []

        for finding in findings:
            result = self.validate_finding(finding)

            # Update finding confidence
            finding.confidence = result.confidence

            # Keep findings above threshold
            if result.is_valid and result.confidence >= min_confidence:
                validated.append(finding)

        return validated

    def get_validation_report(
        self,
        findings: list[Finding],
    ) -> dict:
        """Generate a validation report for findings."""
        results = [self.validate_finding(f) for f in findings]

        high_confidence = [r for r in results if r.confidence >= 0.8]
        medium_confidence = [r for r in results if 0.5 <= r.confidence < 0.8]
        low_confidence = [r for r in results if r.confidence < 0.5]

        return {
            "total": len(findings),
            "high_confidence": len(high_confidence),
            "medium_confidence": len(medium_confidence),
            "low_confidence": len(low_confidence),
            "filtered_out": len([r for r in results if not r.is_valid]),
            "average_confidence": sum(r.confidence for r in results) / len(results) if results else 0,
        }


class CrossValidator:
    """Cross-validates findings by having agents check each other's work."""

    def __init__(self, config):
        self.config = config
        self.validator = FindingValidator()

    def cross_validate(
        self,
        findings: list[Finding],
        file_contents: dict[str, str],
    ) -> list[Finding]:
        """Cross-validate findings against multiple sources."""
        validated = []

        for finding in findings:
            # Check 1: File exists
            if finding.file not in file_contents:
                continue

            # Check 2: Line is valid
            content = file_contents[finding.file]
            lines = content.split('\n')

            if finding.line < 1 or finding.line > len(lines):
                # Try to find the issue by searching
                found = self._search_for_issue(finding, content)
                if found:
                    finding.line = found
                else:
                    finding.line = 1  # Default to file-level

            # Check 3: Issue is present in some form
            result = self.validator.validate_finding(finding)
            if result.confidence >= 0.4:  # Lower threshold for cross-validation
                finding.confidence = result.confidence
                validated.append(finding)

        return validated

    def _search_for_issue(self, finding: Finding, content: str) -> int:
        """Try to find the line where an issue occurs."""
        # Extract potential identifiers from the message
        identifiers = re.findall(r'`([a-zA-Z_][a-zA-Z0-9_]*)`', finding.message)
        identifiers.extend(re.findall(r'function\s+([a-zA-Z_][a-zA-Z0-9_]*)', finding.message))
        identifiers.extend(re.findall(r'variable\s+([a-zA-Z_][a-zA-Z0-9_]*)', finding.message))

        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            for identifier in identifiers:
                if identifier in line:
                    return i

        return 0
