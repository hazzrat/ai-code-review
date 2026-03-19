"""Pattern learning system to improve finding quality over time.

This module learns from codebase patterns and past reviews to improve
the accuracy of findings, especially useful for non-deterministic APIs.
"""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import time


@dataclass
class LearnedPattern:
    """A learned pattern from code reviews."""
    pattern: str
    pattern_type: str  # "bug", "false_positive", "valid", "ignored"
    occurrence_count: int = 1
    last_seen: float = field(default_factory=time.time)
    examples: list[str] = field(default_factory=list)
    confidence_adjustment: float = 0.0  # How to adjust confidence


@dataclass
class CodePattern:
    """A pattern found in code."""
    name: str
    regex: str
    severity: str
    message_template: str
    confidence: float = 0.8
    is_structural: bool = False  # Structural issues are more reliable


class PatternLearner:
    """Learns and applies patterns from code reviews."""

    # High-confidence patterns that should always be reported
    RELIABLE_PATTERNS = [
        CodePattern(
            name="hardcoded_api_key",
            regex=r"(?:api[_-]?key|apikey)\s*[=:]\s*['\"][^'\"]{10,}['\"]",
            severity="bug",
            message_template="Hardcoded API key detected",
            confidence=0.95,
        ),
        CodePattern(
            name="hardcoded_secret",
            regex=r"(?:secret|password|token)\s*[=:]\s*['\"][^'\"]{8,}['\"]",
            severity="bug",
            message_template="Hardcoded secret/credential detected",
            confidence=0.95,
        ),
        CodePattern(
            name="sql_injection_risk",
            regex=r"(?:query|execute)\s*\([^)]*\+\s*[\"']?\$|f['\"].*SELECT.*\{",
            severity="bug",
            message_template="Potential SQL injection vulnerability",
            confidence=0.85,
        ),
        CodePattern(
            name="xss_innerHTML",
            regex=r"\.innerHTML\s*=\s*(?!['\"]\\s*['\"])",
            severity="bug",
            message_template="XSS risk: direct innerHTML assignment",
            confidence=0.9,
        ),
        CodePattern(
            name="dangerous_dangerouslySetInnerHTML",
            regex=r"dangerouslySetInnerHTML\s*=\s*\{[^}]*__html",
            severity="bug",
            message_template="XSS risk: dangerouslySetInnerHTML used",
            confidence=0.9,
        ),
        CodePattern(
            name="eval_usage",
            regex=r"\beval\s*\(",
            severity="bug",
            message_template="Dangerous eval() usage",
            confidence=0.95,
        ),
        CodePattern(
            name="debug_enabled",
            regex=r"debug\s*:\s*true(?!\s*\|\|)",
            severity="nit",
            message_template="Debug mode enabled in configuration",
            confidence=0.85,
        ),
        CodePattern(
            name="console_log_production",
            regex=r"console\.(log|debug|info)\s*\(",
            severity="nit",
            message_template="Console.log in production code",
            confidence=0.7,
        ),
        CodePattern(
            name="env_file_committed",
            regex=r"\.env(?:\.[a-z]+)?(?!\.example)",
            severity="bug",
            message_template="Environment file may contain secrets",
            confidence=0.8,
        ),
        CodePattern(
            name="missing_useEffect_cleanup",
            regex=r"useEffect\s*\([^)]*\)\s*,\s*\[\s*\]",
            severity="nit",
            message_template="useEffect with empty deps may need cleanup",
            confidence=0.5,  # Lower confidence, needs context
        ),
        CodePattern(
            name="localStorage_token",
            regex=r"localStorage\.(setItem|getItem)\s*\([^)]*token",
            severity="nit",
            message_template="Token stored in localStorage (consider httpOnly cookies)",
            confidence=0.75,
        ),
        CodePattern(
            name="firebase_hardcoded",
            regex=r"apiKey\s*:\s*['\"][a-zA-Z0-9_-]{20,}['\"]",
            severity="bug",
            message_template="Firebase API key hardcoded",
            confidence=0.9,
        ),
        CodePattern(
            name="misspelled_function",
            regex=r"(?:validaiton|validaton|validaion)",
            severity="nit",
            message_template="Possible typo in function/variable name",
            confidence=0.8,
        ),
    ]

    # Patterns that often lead to false positives
    FALSE_POSITIVE_INDICATORS = [
        r"might\s+cause",
        r"could\s+potentially",
        r"may\s+lead\s+to",
        r"should\s+consider",
        r"would\s+be\s+better",
        r"optional\s+improvement",
        r"nice\s+to\s+have",
        r"consider\s+adding",
        r"might\s+want",
    ]

    def __init__(self, learning_file: Optional[Path] = None):
        self.learning_file = learning_file or Path.home() / ".code-review-learning.json"
        self.learned_patterns: dict[str, LearnedPattern] = {}
        self.project_patterns: dict[str, list[str]] = defaultdict(list)
        self._load_learned_patterns()

    def _load_learned_patterns(self) -> None:
        """Load previously learned patterns."""
        if self.learning_file.exists():
            try:
                with open(self.learning_file) as f:
                    data = json.load(f)

                for pattern_data in data.get("patterns", []):
                    pattern = LearnedPattern(**pattern_data)
                    self.learned_patterns[pattern.pattern] = pattern

                self.project_patterns = defaultdict(list, data.get("projects", {}))
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_learned_patterns(self) -> None:
        """Save learned patterns to disk."""
        data = {
            "patterns": [
                {
                    "pattern": p.pattern,
                    "pattern_type": p.pattern_type,
                    "occurrence_count": p.occurrence_count,
                    "last_seen": p.last_seen,
                    "examples": p.examples[:5],  # Keep last 5 examples
                    "confidence_adjustment": p.confidence_adjustment,
                }
                for p in self.learned_patterns.values()
            ],
            "projects": dict(self.project_patterns),
        }

        with open(self.learning_file, "w") as f:
            json.dump(data, f, indent=2)

    def scan_with_patterns(
        self,
        file_path: str,
        content: str,
    ) -> list[dict]:
        """Scan content using learned and reliable patterns."""
        findings = []

        for pattern in self.RELIABLE_PATTERNS:
            matches = re.finditer(pattern.regex, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1

                finding = {
                    "file": file_path,
                    "line": line_num,
                    "message": pattern.message_template,
                    "severity": pattern.severity,
                    "confidence": pattern.confidence,
                    "agent": "pattern_learner",
                    "pattern_name": pattern.name,
                }
                findings.append(finding)

        return findings

    def adjust_confidence(
        self,
        finding_message: str,
        initial_confidence: float = 1.0,
    ) -> float:
        """Adjust finding confidence based on learned patterns."""
        message_lower = finding_message.lower()

        # Check for false positive indicators
        for indicator in self.FALSE_POSITIVE_INDICATORS:
            if re.search(indicator, message_lower):
                initial_confidence *= 0.6
                break

        # Check learned patterns
        message_hash = hashlib.md5(finding_message.encode()).hexdigest()[:8]
        if message_hash in self.learned_patterns:
            pattern = self.learned_patterns[message_hash]
            adjustment = pattern.confidence_adjustment
            initial_confidence = initial_confidence * (1 + adjustment)

        return max(0.1, min(1.0, initial_confidence))

    def learn_from_finding(
        self,
        finding: dict,
        accepted: bool = True,
    ) -> None:
        """Learn from a finding's acceptance/rejection."""
        message_hash = hashlib.md5(finding.get("message", "").encode()).hexdigest()[:8]

        if message_hash in self.learned_patterns:
            pattern = self.learned_patterns[message_hash]
            pattern.occurrence_count += 1
            pattern.last_seen = time.time()
        else:
            pattern = LearnedPattern(
                pattern=message_hash,
                pattern_type="valid" if accepted else "false_positive",
                examples=[finding.get("message", "")[:100]],
            )
            self.learned_patterns[message_hash] = pattern

        # Adjust confidence based on feedback
        if accepted:
            pattern.confidence_adjustment = min(0.5, pattern.confidence_adjustment + 0.1)
        else:
            pattern.confidence_adjustment = max(-0.8, pattern.confidence_adjustment - 0.2)

        self._save_learned_patterns()

    def learn_project_patterns(
        self,
        project_name: str,
        patterns: list[str],
    ) -> None:
        """Learn patterns specific to a project."""
        self.project_patterns[project_name] = patterns
        self._save_learned_patterns()

    def get_reliable_findings(
        self,
        findings: list[dict],
        file_contents: dict[str, str],
    ) -> list[dict]:
        """Enhance findings with pattern-based validation."""
        enhanced = []

        for finding in findings:
            # Adjust confidence based on learned patterns
            finding["confidence"] = self.adjust_confidence(
                finding.get("message", ""),
                finding.get("confidence", 1.0),
            )

            # Cross-check with reliable patterns
            file_path = finding.get("file", "")
            if file_path in file_contents:
                content = file_contents[file_path]
                line_num = finding.get("line", 0)

                # Check if the finding's issue is verifiable
                for pattern in self.RELIABLE_PATTERNS:
                    if re.search(pattern.regex, content, re.IGNORECASE):
                        # Finding is supported by a reliable pattern
                        finding["confidence"] = max(
                            finding.get("confidence", 0.5),
                            pattern.confidence,
                        )
                        break

            enhanced.append(finding)

        return enhanced

    def get_stats(self) -> dict:
        """Get learning statistics."""
        return {
            "total_patterns": len(self.learned_patterns),
            "valid_patterns": len([p for p in self.learned_patterns.values() if p.pattern_type == "valid"]),
            "false_positives": len([p for p in self.learned_patterns.values() if p.pattern_type == "false_positive"]),
            "projects_learned": len(self.project_patterns),
            "reliable_patterns_count": len(self.RELIABLE_PATTERNS),
        }
