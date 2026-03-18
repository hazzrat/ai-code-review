"""Finding aggregation and deduplication."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from .config import Config
from .fetcher import FetchedPR
from .agents.base import Finding


@dataclass
class AggregatedFinding:
    """A finding with deduplication metadata."""
    finding: Finding
    duplicates: list[Finding]
    score: float  # Higher is more important


class Aggregator:
    """Aggregates and deduplicates findings from multiple agents."""

    # Severity weights for ranking
    SEVERITY_WEIGHTS = {
        "bug": 3.0,
        "nit": 1.0,
        "pre-existing": 0.5,
    }

    # Minimum similarity for deduplication
    SIMILARITY_THRESHOLD = 0.8

    def __init__(self, config: Config):
        self.config = config

    def _similarity(self, a: str, b: str) -> float:
        """Calculate string similarity using SequenceMatcher."""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _findings_similar(self, a: Finding, b: Finding) -> bool:
        """Check if two findings are similar enough to be duplicates."""
        # Same location
        if a.file != b.file:
            return False

        # Lines within reasonable range
        if abs(a.line - b.line) > 5:
            return False

        # Similar message
        if self._similarity(a.message, b.message) >= self.SIMILARITY_THRESHOLD:
            return True

        # Same issue detected by different agents
        if a.line == b.line and (
            self._similarity(a.message, b.message) >= 0.5
            or any(word in a.message.lower() and word in b.message.lower()
                   for word in ["null", "undefined", "missing", "error", "injection"])
        ):
            return True

        return False

    def _calculate_score(self, finding: Finding) -> float:
        """Calculate importance score for a finding."""
        base_score = self.SEVERITY_WEIGHTS.get(finding.severity, 1.0)

        # Boost for high confidence
        confidence_bonus = finding.confidence * 0.5

        # Boost for security issues
        security_bonus = 0.5 if finding.agent == "security" and finding.severity == "bug" else 0

        return base_score + confidence_bonus + security_bonus

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """Deduplicate similar findings."""
        if not findings:
            return []

        # Group findings by similarity
        groups: list[list[Finding]] = []

        for finding in findings:
            matched = False
            for group in groups:
                if any(self._findings_similar(finding, f) for f in group):
                    group.append(finding)
                    matched = True
                    break

            if not matched:
                groups.append([finding])

        # Select best finding from each group
        deduplicated = []
        for group in groups:
            # Sort by score and severity
            group.sort(key=lambda f: (
                self.SEVERITY_WEIGHTS.get(f.severity, 0),
                f.confidence,
                len(f.message),
            ), reverse=True)

            # Take the best one
            best = group[0]

            # If multiple agents found the same issue, note it
            if len(group) > 1:
                agents = list(set(f.agent for f in group))
                best.reasoning = f"[{', '.join(agents)}] {best.reasoning}"

            deduplicated.append(best)

        return deduplicated

    def filter_by_threshold(self, findings: list[Finding]) -> list[Finding]:
        """Filter findings by severity threshold."""
        threshold = self.config.review.severity_threshold

        if threshold == "all":
            return findings

        severity_order = ["bug", "nit", "pre-existing"]
        threshold_idx = severity_order.index(threshold) if threshold in severity_order else 0

        return [
            f for f in findings
            if f.severity in severity_order
            and severity_order.index(f.severity) <= threshold_idx
        ]

    def rank(self, findings: list[Finding]) -> list[Finding]:
        """Rank findings by importance."""
        return sorted(
            findings,
            key=lambda f: self._calculate_score(f),
            reverse=True,
        )

    def validate_lines(self, findings: list[Finding], pr_data: FetchedPR) -> list[Finding]:
        """Validate that finding lines exist in the diff."""
        valid_lines = {}

        for diff in pr_data.diffs:
            valid_lines[diff.new_path] = set()
            for hunk in diff.hunks:
                for change_type, line_num, content in hunk.changes:
                    if change_type in ("+", " "):
                        valid_lines[diff.new_path].add(line_num)

        validated = []
        for finding in findings:
            if finding.file not in valid_lines:
                # File might have different path format, try fuzzy match
                matched_file = None
                for path in valid_lines:
                    if path.endswith(finding.file) or finding.file.endswith(path):
                        matched_file = path
                        break

                if matched_file:
                    finding.file = matched_file
                else:
                    # File not in diff, adjust line to 0 (will be PR-level comment)
                    finding.line = 0

            # Check if line is in valid lines
            if finding.file in valid_lines and finding.line not in valid_lines[finding.file]:
                # Try to find nearest valid line
                lines = sorted(valid_lines[finding.file])
                for line in lines:
                    if abs(line - finding.line) <= 3:
                        finding.line = line
                        break
                else:
                    finding.line = 0

            validated.append(finding)

        return validated

    def aggregate(
        self,
        findings: list[Finding],
        pr_data: Optional[FetchedPR] = None,
    ) -> list[Finding]:
        """Main aggregation pipeline.

        1. Validate line numbers
        2. Deduplicate similar findings
        3. Filter by severity threshold
        4. Rank by importance
        """
        if pr_data:
            findings = self.validate_lines(findings, pr_data)

        findings = self.deduplicate(findings)
        findings = self.filter_by_threshold(findings)
        findings = self.rank(findings)

        return findings

    def generate_summary(self, findings: list[Finding]) -> str:
        """Generate a summary of findings."""
        if not findings:
            return "✅ No issues found in this PR."

        bugs = [f for f in findings if f.severity == "bug"]
        nits = [f for f in findings if f.severity == "nit"]
        preexisting = [f for f in findings if f.severity == "pre-existing"]

        lines = ["## Code Review Summary\n"]

        if bugs:
            lines.append(f"### 🔴 Bugs ({len(bugs)})\n")
            for f in bugs[:5]:  # Top 5
                lines.append(f"- **{f.file}:{f.line}** - {f.message}")
            if len(bugs) > 5:
                lines.append(f"- ... and {len(bugs) - 5} more")
            lines.append("")

        if nits:
            lines.append(f"### 🟡 Suggestions ({len(nits)})\n")
            for f in nits[:5]:
                lines.append(f"- **{f.file}:{f.line}** - {f.message}")
            if len(nits) > 5:
                lines.append(f"- ... and {len(nits) - 5} more")
            lines.append("")

        if preexisting:
            lines.append(f"### 🟣 Pre-existing Issues ({len(preexisting)})\n")
            lines.append("Some issues were found that appear to pre-exist in the codebase.")
            lines.append("")

        return "\n".join(lines)
