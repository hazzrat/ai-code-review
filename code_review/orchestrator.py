"""Agent orchestration and parallel execution."""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from .config import Config
from .fetcher import FetchedPR, FileDiff
from .agents.base import AgentContext, Finding
from .agents.logic import LogicAgent
from .agents.security import SecurityAgent
from .agents.edge_cases import EdgeCasesAgent
from .agents.types import TypesAgent
from .agents.regression import RegressionAgent
from .agents.verification import VerificationAgent
from .agents.claude_md_check import ClaudeMdAgent
from .agents.react_ts import ReactTSAgent
from .agents.architecture import ArchitectureAgent
from .agents.performance import PerformanceAgent
from .agents.documentation import DocumentationAgent
from .agents.testing import TestingAgent
from .agents.accessibility import AccessibilityAgent
from .agents.database import DatabaseAgent
from .consensus import ConsensusEngine, ConsensusFinding
from .cache import FindingCache


@dataclass
class AgentResult:
    """Result from a single agent run."""
    agent_name: str
    findings: list[Finding]
    error: Optional[str] = None
    duration_ms: int = 0


AGENT_CLASSES = {
    "logic": LogicAgent,
    "security": SecurityAgent,
    "edge_cases": EdgeCasesAgent,
    "types": TypesAgent,
    "regression": RegressionAgent,
    "claude_md": ClaudeMdAgent,
    "react_ts": ReactTSAgent,
    "architecture": ArchitectureAgent,
    "performance": PerformanceAgent,
    "documentation": DocumentationAgent,
    "testing": TestingAgent,
    "accessibility": AccessibilityAgent,
    "database": DatabaseAgent,
}


class Orchestrator:
    """Orchestrates parallel execution of code review agents."""

    def __init__(self, config: Config):
        self.config = config
        self.agents = self._init_agents()

    def _init_agents(self) -> dict:
        """Initialize enabled agents."""
        agents = {}
        enabled_names = self.config.get_enabled_agents()

        for name, agent_class in AGENT_CLASSES.items():
            if name in enabled_names:
                agents[name] = agent_class(self.config)

        return agents

    def _build_diff_text(self, diffs: list[FileDiff]) -> str:
        """Convert FileDiff list to unified diff text."""
        lines = []

        for diff in diffs:
            lines.append(f"diff --git a/{diff.old_path} b/{diff.new_path}")

            if diff.status == "added":
                lines.append("new file mode 100644")
            elif diff.status == "deleted":
                lines.append("deleted file mode 100644")

            lines.append(f"--- a/{diff.old_path}")
            lines.append(f"+++ b/{diff.new_path}")

            for hunk in diff.hunks:
                old_range = f"-{hunk.old_start}"
                if hunk.old_count > 1:
                    old_range += f",{hunk.old_count}"

                new_range = f"+{hunk.new_start}"
                if hunk.new_count > 1:
                    new_range += f",{hunk.new_count}"

                lines.append(f"@@ {old_range} {new_range} @@")

                for change_type, line_num, content in hunk.changes:
                    if change_type == "+":
                        lines.append(f"+{content}")
                    elif change_type == "-":
                        lines.append(f"-{content}")
                    else:
                        lines.append(f" {content}")

            lines.append("")

        return "\n".join(lines)

    def _build_context(self, pr_data: FetchedPR) -> AgentContext:
        """Build agent context from fetched PR data."""
        diff_text = self._build_diff_text(pr_data.diffs)

        return AgentContext(
            diff_text=diff_text,
            file_contents=pr_data.file_contents,
            context_files=pr_data.context_files,
            review_rules=self.config.review_rules,
            pr_title=pr_data.info.title if pr_data.info else "",
            pr_body=pr_data.info.body if pr_data.info else "",
            claude_md=self.config.claude_md.content if self.config.claude_md else "",
        )

    def _run_agent(
        self,
        name: str,
        context: AgentContext,
    ) -> AgentResult:
        """Run a single agent and return results."""
        import time

        agent = self.agents.get(name)
        if not agent:
            return AgentResult(
                agent_name=name,
                findings=[],
                error=f"Agent {name} not found",
            )

        start = time.time()
        try:
            findings = agent.analyze(context)
            duration = int((time.time() - start) * 1000)

            return AgentResult(
                agent_name=name,
                findings=findings,
                duration_ms=duration,
            )
        except ValueError as e:
            # Handle configuration errors (like missing API key)
            duration = int((time.time() - start) * 1000)
            return AgentResult(
                agent_name=name,
                findings=[],
                error=str(e),
                duration_ms=duration,
            )
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            # Extract the root cause from retry errors
            error_msg = str(e)

            # Handle tenacity RetryError - extract inner exception
            if type(e).__name__ == 'RetryError' and e.args:
                try:
                    future = e.args[0]
                    if hasattr(future, 'exception'):
                        inner = future.exception()
                        if inner:
                            error_msg = str(inner)
                except (AttributeError, IndexError):
                    pass

            return AgentResult(
                agent_name=name,
                findings=[],
                error=error_msg,
                duration_ms=duration,
            )

    def run(
        self,
        pr_data: FetchedPR,
        specific_agents: Optional[list[str]] = None,
    ) -> list[Finding]:
        """Run all agents in parallel and collect findings.

        Args:
            pr_data: Fetched PR data
            specific_agents: Optional list of specific agents to run

        Returns:
            Combined list of all findings
        """
        context = self._build_context(pr_data)

        # Check diff size
        if len(context.diff_text) > self.config.review.max_diff_size:
            # Fall back to summary mode for large diffs
            context.diff_text = context.diff_text[:self.config.review.max_diff_size]
            context.diff_text += "\n\n... [truncated due to size]"

        # Determine which agents to run
        agents_to_run = specific_agents if specific_agents else list(self.agents.keys())

        if self.config.output.verbose:
            print(f"Running agents: {', '.join(agents_to_run)}")

        # Run agents in parallel using ThreadPoolExecutor
        all_findings = []

        with ThreadPoolExecutor(max_workers=len(agents_to_run)) as executor:
            futures = {
                executor.submit(self._run_agent, name, context): name
                for name in agents_to_run
            }

            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    result = future.result()

                    if self.config.output.verbose:
                        status = f"{len(result.findings)} findings"
                        if result.error:
                            status = f"error: {result.error}"
                        print(f"  {agent_name}: {status} ({result.duration_ms}ms)")

                    all_findings.extend(result.findings)

                except Exception as e:
                    error_msg = str(e)
                    # Handle tenacity RetryError - extract the inner exception
                    try:
                        exc_type_name = type(e).__name__
                        if exc_type_name == 'RetryError' and e.args:
                            future = e.args[0]
                            if hasattr(future, 'exception'):
                                inner = future.exception()
                                if inner:
                                    error_msg = str(inner)
                    except (AttributeError, IndexError):
                        pass

                    # Check for missing API key error
                    if "No API key found" in error_msg:
                        if self.config.output.verbose:
                            print(f"  {agent_name}: error: Missing API key")
                            print(f"    Set CODE_REVIEW_API_KEY or ANTHROPIC_API_KEY environment variable")
                    elif self.config.output.verbose:
                        # Truncate long error messages
                        display_msg = error_msg[:150] if len(error_msg) > 150 else error_msg
                        print(f"  {agent_name}: error: {display_msg}")

        return all_findings

    async def run_async(
        self,
        pr_data: FetchedPR,
        specific_agents: Optional[list[str]] = None,
    ) -> list[Finding]:
        """Async version of run() for integration with async frameworks."""
        import functools
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(self.run, pr_data, specific_agents),
        )

    def run_with_verification(
        self,
        pr_data: FetchedPR,
        specific_agents: Optional[list[str]] = None,
    ) -> list[Finding]:
        """Run agents and verify findings.

        Args:
            pr_data: Fetched PR data
            specific_agents: Optional list of specific agents to run

        Returns:
            Verified list of findings
        """
        # Get raw findings from all agents
        raw_findings = self.run(pr_data, specific_agents)

        if not self.config.verification.enabled:
            return raw_findings

        # Run verification agent
        context = self._build_context(pr_data)
        verification_agent = VerificationAgent(self.config)

        verified_findings = verification_agent.verify(
            raw_findings,
            context,
            self.config.verification.confidence_threshold,
        )

        if self.config.output.verbose:
            print(f"Verification: {len(raw_findings)} → {len(verified_findings)} findings")

        return verified_findings

    def run_with_consensus(
        self,
        pr_data: FetchedPR,
        specific_agents: Optional[list[str]] = None,
    ) -> tuple[list[Finding], dict]:
        """Run agents with multi-pass consensus for deterministic results.

        This runs the review multiple times and only reports findings that
        appear consistently across passes.

        Args:
            pr_data: Fetched PR data
            specific_agents: Optional list of specific agents to run

        Returns:
            Tuple of (findings, consensus_report)
        """
        if not self.config.consensus.enabled:
            # Fall back to single pass
            return self.run(pr_data, specific_agents), {}

        context = self._build_context(pr_data)

        # Check diff size
        if len(context.diff_text) > self.config.review.max_diff_size:
            context.diff_text = context.diff_text[:self.config.review.max_diff_size]
            context.diff_text += "\n\n... [truncated due to size]"

        # Determine which agents to run
        agents_to_run = specific_agents if specific_agents else list(self.agents.keys())

        # Initialize consensus engine
        consensus_engine = ConsensusEngine(self.config)

        if self.config.output.verbose:
            print(f"Running {self.config.consensus.passes} passes for consensus...")

        # Run multiple passes
        all_pass_findings = []
        for pass_num in range(1, self.config.consensus.passes + 1):
            if self.config.output.verbose:
                print(f"\n--- Pass {pass_num}/{self.config.consensus.passes} ---")

            pass_findings = self.run(pr_data, specific_agents)
            all_pass_findings.append(pass_findings)

        # Aggregate findings with consensus
        consensus_findings, report = consensus_engine.aggregate(all_pass_findings)

        # Filter by threshold
        threshold = self.config.consensus.threshold
        filtered_findings = [
            cf.finding for cf in consensus_findings
            if cf.consensus_score >= threshold
        ]

        if self.config.output.verbose:
            print(f"\nConsensus Report:")
            print(f"  Total unique findings: {len(consensus_findings)}")
            print(f"  Findings above threshold ({threshold}): {len(filtered_findings)}")
            print(f"  Average consensus score: {report.get('average_score', 0):.2f}")

        return filtered_findings, report
