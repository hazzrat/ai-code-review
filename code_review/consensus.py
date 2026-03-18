"""Multi-pass consensus for deterministic code review results.

This module implements consensus-based finding aggregation to ensure
consistent and reliable results across multiple AI passes.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from .agents.base import Finding, AgentContext
from .config import Config, ConsensusConfig
from .cache import FindingCache


@dataclass
class ConsensusFinding:
    """A finding with consensus metadata."""
    finding: Finding
    pass_count: int  # Number of passes that found this
    total_passes: int  # Total number of passes
    consensus_score: float  # pass_count / total_passes

    @property
    def is_consensus(self) -> bool:
        """Check if this finding meets the consensus threshold."""
        return self.consensus_score >= 0.5  # Found in at least half of passes


class ConsensusEngine:
    """Engine for running multi-pass consensus on findings."""

    def __init__(self, config: Config):
        self.config = config
        self.consensus_config = config.consensus
        self.cache = FindingCache() if config.cache.enabled else None

    def _finding_signature(self, finding: Finding) -> str:
        """Create a unique signature for a finding to compare across passes."""
        # Normalize the finding for comparison
        normalized = f"{finding.file}:{finding.line}:{finding.severity}:{finding.message[:100]}"
        return hashlib.md5(normalized.encode()).hexdigest()

    def _findings_similar(self, f1: Finding, f2: Finding) -> bool:
        """Check if two findings are similar enough to be considered the same."""
        # Same file and line
        if f1.file != f2.file or f1.line != f2.line:
            return False

        # Same severity
        if f1.severity != f2.severity:
            return False

        # Similar message (at least 50% word overlap)
        words1 = set(f1.message.lower().split())
        words2 = set(f2.message.lower().split())
        if not words1 or not words2:
            return False

        overlap = len(words1 & words2)
        max_words = max(len(words1), len(words2))
        return overlap / max_words >= 0.5

    def _aggregate_findings(
        self,
        all_pass_findings: list[list[Finding]],
    ) -> list[ConsensusFinding]:
        """Aggregate findings across multiple passes."""
        # Group similar findings
        finding_groups: list[tuple[Finding, list[int]]] = []

        for pass_idx, pass_findings in enumerate(all_pass_findings):
            for finding in pass_findings:
                # Check if this finding matches any existing group
                matched = False
                for i, (representative, pass_indices) in enumerate(finding_groups):
                    if self._findings_similar(finding, representative):
                        pass_indices.append(pass_idx)
                        matched = True
                        break

                if not matched:
                    finding_groups.append((finding, [pass_idx]))

        # Convert to consensus findings
        total_passes = len(all_pass_findings)
        consensus_findings = []

        for representative, pass_indices in finding_groups:
            consensus = ConsensusFinding(
                finding=representative,
                pass_count=len(pass_indices),
                total_passes=total_passes,
                consensus_score=len(pass_indices) / total_passes,
            )

            # Update the finding's confidence based on consensus
            representative.confidence = consensus.consensus_score

            consensus_findings.append(consensus)

        return consensus_findings

    def aggregate(
        self,
        all_pass_findings: list[list[Finding]],
    ) -> tuple[list[ConsensusFinding], dict]:
        """Aggregate findings from multiple passes and return with report.

        Args:
            all_pass_findings: List of findings from each pass

        Returns:
            Tuple of (consensus_findings, report)
        """
        consensus_findings = self._aggregate_findings(all_pass_findings)
        report = self.get_consensus_report(consensus_findings)
        return consensus_findings, report

    def run_with_consensus(
        self,
        context: AgentContext,
        agent_analyze_func: Callable[[AgentContext], list[Finding]],
        agent_name: str,
    ) -> list[Finding]:
        """Run agent analysis multiple times and return consensus findings.

        Args:
            context: Agent context for analysis
            agent_analyze_func: Function to run agent analysis
            agent_name: Name of the agent for caching

        Returns:
            List of consensus findings
        """
        if not self.consensus_config.enabled:
            # Single pass if consensus disabled
            return agent_analyze_func(context)

        # Check cache first
        cache_key = None
        if self.cache:
            cache_key = self._create_cache_key(context, agent_name)
            cached = self.cache.get(cache_key)
            if cached:
                # Return cached findings with consensus
                return [
                    f.finding for f in cached
                    if f.consensus_score >= self.consensus_config.threshold
                ]

        # Run multiple passes
        all_pass_findings = []
        for pass_idx in range(self.consensus_config.passes):
            findings = agent_analyze_func(context)
            all_pass_findings.append(findings)

        # Aggregate and compute consensus
        consensus_findings = self._aggregate_findings(all_pass_findings)

        # Filter by threshold
        filtered_findings = [
            cf for cf in consensus_findings
            if cf.consensus_score >= self.consensus_config.threshold
        ]

        # Cache results
        if self.cache and cache_key:
            self.cache.set(cache_key, consensus_findings, agent_name)

        # Return only the findings that meet threshold
        return [cf.finding for cf in filtered_findings]

    def _create_cache_key(self, context: AgentContext, agent_name: str) -> str:
        """Create a cache key from context."""
        content = f"{agent_name}:{context.diff_text}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def get_consensus_report(
        self,
        consensus_findings: list[ConsensusFinding],
    ) -> dict:
        """Generate a report about consensus quality."""
        if not consensus_findings:
            return {
                "total_findings": 0,
                "high_consensus": 0,
                "medium_consensus": 0,
                "low_consensus": 0,
                "average_score": 0.0,
            }

        high = sum(1 for cf in consensus_findings if cf.consensus_score >= 0.8)
        medium = sum(1 for cf in consensus_findings if 0.6 <= cf.consensus_score < 0.8)
        low = sum(1 for cf in consensus_findings if cf.consensus_score < 0.6)

        return {
            "total_findings": len(consensus_findings),
            "high_consensus": high,
            "medium_consensus": medium,
            "low_consensus": low,
            "average_score": sum(cf.consensus_score for cf in consensus_findings) / len(consensus_findings),
            "total_passes": self.consensus_config.passes,
        }
