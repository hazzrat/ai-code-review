"""CLI entry point for code review system."""

import argparse
import json
import sys
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm

from .config import Config, load_config
from .fetcher import fetch_pr, fetch_local_diff, fetch_local_files, FetchedPR
from .orchestrator import Orchestrator
from .aggregator import Aggregator
from .poster import CommentPoster
from .auto_resolve import AutoResolver
from .analytics import AnalyticsTracker, ReviewMetrics
from .learner import Learner
from .context_analyzer import ContextAnalyzer


console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        prog="claude_review",
        description="Claude Code Review - Multi-agent AI code review system",
    )

    # Positional argument: path to repo or PR URL
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Path to local repo, PR URL, or '.' for current directory",
    )

    # Review modes
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Review only changes (diff mode) instead of full codebase",
    )

    parser.add_argument(
        "--base",
        default="main",
        help="Base branch for diff review (default: main)",
    )

    # Output options
    parser.add_argument(
        "--output",
        choices=["console", "json", "markdown"],
        default="console",
        help="Output format (default: console)",
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        help="Interactively fix issues after review",
    )

    parser.add_argument(
        "--auto-fix",
        action="store_true",
        help="Automatically fix simple issues without confirmation",
    )

    parser.add_argument(
        "--learn",
        action="store_true",
        help="Learn from codebase patterns for future reviews",
    )

    # Agent selection
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=["logic", "security", "edge_cases", "types", "regression", "claude_md", "react_ts", "architecture", "performance", "documentation", "testing", "accessibility", "database"],
        help="Specific agents to run (default: all)",
    )

    parser.add_argument(
        "--severity",
        choices=["bug", "nit", "all"],
        default="all",
        help="Minimum severity threshold for findings",
    )

    # Other options
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to config.yaml file",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output",
    )

    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the summary table",
    )

    # Deterministic mode options
    parser.add_argument(
        "--consensus",
        action="store_true",
        help="Enable multi-pass consensus mode for more deterministic results",
    )

    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Enable fully deterministic mode (low temperature + consensus + seed)",
    )

    parser.add_argument(
        "--passes",
        type=int,
        default=3,
        help="Number of consensus passes (default: 3)",
    )

    parser.add_argument(
        "--robust",
        action="store_true",
        help="Enable robust mode for non-deterministic APIs (combines pattern scanning, consensus, validation, and learning)",
    )

    parser.add_argument(
        "--no-validation",
        action="store_true",
        help="Disable finding validation (faster but less accurate)",
    )

    return parser


def scan_codebase(repo_path: Path) -> dict[str, str]:
    """Scan entire codebase and return file contents."""
    files = {}
    ignore_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build', '.next', 'coverage'}
    ignore_exts = {'.pyc', '.pyo', '.so', '.dylib', '.dll', '.exe', '.bin', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.woff', '.woff2', '.ttf', '.eot', '.mp4', '.mp3', '.wav', '.pdf', '.zip', '.tar', '.gz', '.lock'}

    for root, dirs, filenames in os.walk(repo_path):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for filename in filenames:
            filepath = Path(root) / filename

            # Skip ignored extensions
            if filepath.suffix.lower() in ignore_exts:
                continue

            # Skip large files (>100KB)
            try:
                if filepath.stat().st_size > 100 * 1024:
                    continue
            except OSError:
                continue

            try:
                content = filepath.read_text(encoding='utf-8', errors='ignore')
                relative_path = filepath.relative_to(repo_path)
                files[str(relative_path)] = content
            except Exception:
                continue

    return files


def generate_fix(finding, file_content: str) -> Optional[str]:
    """Generate a fix for a finding using the API."""
    # This would call the LLM to generate a fix
    # For now, return the suggestion if available
    return getattr(finding, 'suggestion', None)


def apply_fix(file_path: Path, finding, fix: str) -> bool:
    """Apply a fix to a file."""
    try:
        content = file_path.read_text()
        lines = content.split('\n')

        if finding.line > 0 and finding.line <= len(lines):
            # Insert the fix as a comment above the problematic line
            lines.insert(finding.line - 1, f"// FIX: {fix}")
            file_path.write_text('\n'.join(lines))
            return True
    except Exception:
        pass
    return False


def print_findings_console(findings: list, verbose: bool = False, show_summary: bool = True) -> None:
    """Print findings to console with rich formatting."""
    if not findings:
        console.print(Panel("[green]✓ No issues found! Your code looks great.[/green]", title="Code Review", border_style="green"))
        return

    # Group by severity
    bugs = [f for f in findings if f.severity == "bug"]
    nits = [f for f in findings if f.severity == "nit"]
    preexisting = [f for f in findings if f.severity == "pre-existing"]

    console.print()

    if bugs:
        console.print(Panel(f"[red bold]🔴 Critical Issues ({len(bugs)})[/red bold]", border_style="red"))
        for i, f in enumerate(bugs, 1):
            console.print(f"\n[red bold]{i}. {f.file}:{f.line}[/red bold]")
            console.print(f"   [red]{f.message}[/red]")
            if f.suggestion:
                console.print(f"   [green]💡 Fix: {f.suggestion}[/green]")
            if verbose and f.reasoning:
                console.print(f"   [dim]Reasoning: {f.reasoning}[/dim]")

    if nits:
        console.print(Panel(f"\n[yellow bold]🟡 Suggestions ({len(nits)})[/yellow bold]", border_style="yellow"))
        for i, f in enumerate(nits, 1):
            console.print(f"\n[yellow bold]{i}. {f.file}:{f.line}[/yellow bold]")
            console.print(f"   [yellow]{f.message}[/yellow]")
            if f.suggestion:
                console.print(f"   [green]💡 Fix: {f.suggestion}[/green]")

    if preexisting:
        console.print(Panel(f"\n[purple bold]🟣 Pre-existing Issues ({len(preexisting)})[/purple bold]", border_style="purple"))
        for f in preexisting[:5]:  # Limit to 5
            console.print(f"  [purple]•[/purple] {f.file}:{f.line} - {f.message}")
        if len(preexisting) > 5:
            console.print(f"  [dim]... and {len(preexisting) - 5} more[/dim]")

    # Summary table
    if show_summary:
        console.print()
        table = Table(title="📊 Review Summary", show_header=True, header_style="bold")
        table.add_column("Category", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Action", justify="center")

        table.add_row("🔴 Critical", str(len(bugs)), "Fix required" if bugs else "✓")
        table.add_row("🟡 Suggestions", str(len(nits)), "Consider fixing" if nits else "✓")
        table.add_row("🟣 Pre-existing", str(len(preexisting)), "Lower priority")
        table.add_row("[bold]Total[/bold]", f"[bold]{len(findings)}[/bold]", "")

        console.print(table)


def interactive_fix_mode(findings: list, repo_path: Path) -> None:
    """Interactive mode to fix issues one by one."""
    console.print("\n[bold blue]🔧 Interactive Fix Mode[/bold blue]")
    console.print("[dim]Review each issue and choose to fix, skip, or see more details[/dim]\n")

    fixed_count = 0
    skipped_count = 0

    for i, finding in enumerate(findings, 1):
        if finding.severity != "bug":
            continue  # Only fix bugs in auto mode

        console.print(f"\n[bold]━━━ Issue {i}/{len(findings)} ━━━[/bold]")
        console.print(f"[red]File:[/red] {finding.file}:{finding.line}")
        console.print(f"[red]Issue:[/red] {finding.message}")

        if finding.suggestion:
            console.print(f"\n[green]Suggested Fix:[/green]")
            console.print(Panel(finding.suggestion, border_style="green"))

        if finding.reasoning:
            console.print(f"[dim]Reasoning: {finding.reasoning}[/dim]")

        choice = Prompt.ask(
            "\nAction",
            choices=["f", "s", "d", "q"],
            default="s",
            show_choices=True,
            show_default=True
        )

        if choice == "f":  # Fix
            file_path = repo_path / finding.file
            if file_path.exists():
                # For now, just show what would be fixed
                console.print(f"[yellow]Opening {finding.file} for editing...[/yellow]")
                console.print(f"[green]Fix applied (placeholder - implement actual fix logic)[/green]")
                fixed_count += 1
            else:
                console.print("[red]File not found[/red]")
        elif choice == "s":  # Skip
            skipped_count += 1
            console.print("[dim]Skipped[/dim]")
        elif choice == "d":  # Details
            console.print(Panel(finding.reasoning or "No additional details", title="Details"))
        elif choice == "q":  # Quit
            break

    console.print(f"\n[bold]Fix Session Complete[/bold]")
    console.print(f"  Fixed: {fixed_count}")
    console.print(f"  Skipped: {skipped_count}")


def main(args: Optional[list[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    opts = parser.parse_args(args)

    # Load configuration
    config = load_config(config_path=opts.config)

    # Apply CLI overrides
    if opts.verbose:
        config.output.verbose = True
    if opts.severity:
        config.review.severity_threshold = opts.severity

    # Apply deterministic mode settings
    if opts.deterministic:
        config.api.temperature = 0.0  # Fully deterministic
        config.api.seed = 42  # Fixed seed
        config.consensus.enabled = True
        config.consensus.passes = opts.passes
        if config.output.verbose:
            console.print("[dim]Deterministic mode: temperature=0.0, seed=42, consensus enabled[/dim]")
    elif opts.consensus:
        config.consensus.enabled = True
        config.consensus.passes = opts.passes
        if config.output.verbose:
            console.print(f"[dim]Consensus mode: {opts.passes} passes, threshold={config.consensus.threshold}[/dim]")

    try:
        # Determine the target
        target = opts.target

        # Check if it's a PR URL
        if target.startswith("http") or ("/pull/" in target):
            console.print(f"[blue]Fetching PR: {target}[/blue]")
            pr_data = fetch_pr(target)
            repo_path = Path.cwd()  # Use current directory as base
        # Check if it's a local path
        else:
            repo_path = Path(target).resolve()
            if not repo_path.exists():
                console.print(f"[red]Error: Path not found: {repo_path}[/red]")
                return 2

            console.print(f"[blue]Scanning: {repo_path}[/blue]")

            if opts.diff:
                # Diff mode: only review changes
                console.print(f"[dim]Diff mode: comparing against {opts.base}[/dim]")
                diffs = fetch_local_diff(opts.base, str(repo_path))
                file_contents = fetch_local_files(diffs)
                pr_data = FetchedPR(
                    info=None,
                    diffs=diffs,
                    file_contents=file_contents,
                    context_files={},
                )
                all_files = file_contents
            else:
                # Full mode: review entire codebase
                console.print("[dim]Full review mode: scanning entire codebase[/dim]")

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task = progress.add_task("Scanning files...", total=None)
                    all_files = scan_codebase(repo_path)

                console.print(f"[dim]Found {len(all_files)} files[/dim]")

                # Create a synthetic diff-like structure for the orchestrator
                from .fetcher import FileDiff, DiffHunk

                synthetic_diffs = []
                for filepath, content in all_files.items():
                    lines = content.split('\n')
                    changes = [('+', i+1, line) for i, line in enumerate(lines)]
                    synthetic_diffs.append(FileDiff(
                        old_path=filepath,
                        new_path=filepath,
                        status="modified",
                        hunks=[DiffHunk(1, 0, 1, len(lines), "", changes)]
                    ))

                pr_data = FetchedPR(
                    info=None,
                    diffs=synthetic_diffs,
                    file_contents=all_files,
                    context_files={},
                )

        # Initialize learner and context analyzer for enhanced analysis
        learner = Learner()
        context_analyzer = ContextAnalyzer(str(repo_path))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Build dependency graph and learn patterns
            task1 = progress.add_task("Building context graph...", total=None)
            context_map = context_analyzer.build_context(all_files)

            task2 = progress.add_task("Learning codebase patterns...", total=None)
            learned_patterns = learner.analyze_codebase(all_files)

        if config.output.verbose:
            console.print(f"[dim]Context: {len(context_map.get('core_modules', []))} core modules, {len(context_map.get('entry_points', []))} entry points[/dim]")
            console.print(f"[dim]Patterns: {learned_patterns.get('naming_conventions', {})} naming conventions learned[/dim]")

        # Apply robust mode settings
        if opts.robust:
            config.consensus.enabled = True
            config.consensus.passes = opts.passes
            if config.output.verbose:
                console.print(f"[dim]Robust mode: pattern scanning + consensus ({opts.passes} passes) + validation + learning[/dim]")

        # Run agents
        orchestrator = Orchestrator(config, repo_path=repo_path)
        consensus_report = {}
        robust_report = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            if opts.robust:
                task = progress.add_task(f"Running robust review...", total=None)
                raw_findings, robust_report = orchestrator.run_robust(pr_data, specific_agents=opts.agents)
                if config.output.verbose:
                    console.print(f"[dim]Robust: {robust_report.get('final_findings', 0)} findings (patterns: {robust_report.get('pattern_findings', 0)})[/dim]")
            elif config.consensus.enabled:
                task = progress.add_task(f"Running consensus review ({config.consensus.passes} passes)...", total=None)
                raw_findings, consensus_report = orchestrator.run_with_consensus(pr_data, specific_agents=opts.agents)
                if config.output.verbose:
                    console.print(f"[dim]Consensus: {consensus_report.get('total_findings', 0)} unique findings, avg score: {consensus_report.get('average_score', 0):.2f}[/dim]")
            else:
                task = progress.add_task("Running review agents...", total=None)
                raw_findings = orchestrator.run(pr_data, specific_agents=opts.agents)

        if config.output.verbose:
            console.print(f"[dim]Agents found {len(raw_findings)} potential issues[/dim]")

        # Verify and aggregate findings
        aggregator = Aggregator(config)
        findings = aggregator.aggregate(raw_findings, pr_data)

        # Apply learned preferences to filter findings
        filtered_findings = []
        for finding in findings:
            should_report, confidence = learner.should_report(finding.message, finding.agent)
            if should_report:
                filtered_findings.append(finding)
            elif config.output.verbose:
                console.print(f"[dim]Filtered out (confidence: {confidence:.2f}): {finding.message[:50]}...[/dim]")

        findings = filtered_findings

        # Filter by severity
        if opts.severity == "bug":
            findings = [f for f in findings if f.severity == "bug"]
        elif opts.severity == "nit":
            findings = [f for f in findings if f.severity in ("bug", "nit")]

        # Output results
        if opts.output == "json":
            print_findings_json(findings)
        elif opts.output == "markdown":
            print_findings_markdown(findings)
        else:
            print_findings_console(findings, config.output.verbose, not opts.no_summary)

        # Interactive fix mode
        if opts.fix and findings:
            interactive_fix_mode(findings, repo_path)

        # Auto-fix mode
        elif opts.auto_fix:
            bugs = [f for f in findings if f.severity == "bug"]
            console.print(f"\n[yellow]Auto-fixing {len(bugs)} critical issues...[/yellow]")
            # Placeholder - implement actual auto-fix logic
            console.print("[dim]Auto-fix not yet implemented[/dim]")

        # Show learned patterns summary
        if opts.learn:
            summary = learner.get_learned_patterns_summary()
            console.print("\n[bold blue]📚 Learning Summary[/bold blue]")
            console.print(f"  Total patterns learned: {summary['total_patterns']}")
            console.print(f"  User preferences stored: {summary['total_preferences']}")
            if summary['top_patterns']:
                console.print("\n  Top patterns by occurrence:")
                for name, count in summary['top_patterns'][:5]:
                    console.print(f"    • {name}: {count} occurrences")

        # Return exit code based on findings
        bug_count = len([f for f in findings if f.severity == "bug"])
        if bug_count > 0:
            console.print(f"\n[yellow]⚠ Found {bug_count} critical issue(s) that need attention[/yellow]")
            return 1

        console.print("\n[green]✓ All checks passed![/green]")
        return 0

    except Exception as e:
        error_msg = str(e).replace("[", "\\[").replace("]", "\\]")
        console.print(f"[red]Error:[/red] {error_msg}")
        if config.output.verbose:
            import traceback
            traceback.print_exc()
        return 2


def print_findings_json(findings: list) -> None:
    """Print findings as JSON."""
    output = {
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "message": f.message,
                "reasoning": f.reasoning,
                "suggestion": getattr(f, 'suggestion', None),
                "agent": f.agent,
            }
            for f in findings
        ],
        "summary": {
            "bugs": len([f for f in findings if f.severity == "bug"]),
            "nits": len([f for f in findings if f.severity == "nit"]),
            "preexisting": len([f for f in findings if f.severity == "pre-existing"]),
            "total": len(findings),
        },
    }
    print(json.dumps(output, indent=2))


def print_findings_markdown(findings: list) -> None:
    """Print findings as Markdown."""
    print("# Code Review Results\n")

    bugs = [f for f in findings if f.severity == "bug"]
    nits = [f for f in findings if f.severity == "nit"]
    preexisting = [f for f in findings if f.severity == "pre-existing"]

    if bugs:
        print("## 🔴 Critical Issues\n")
        for f in bugs:
            print(f"- **{f.file}:{f.line}** - {f.message}")
            suggestion = getattr(f, 'suggestion', None)
            if suggestion:
                print(f"  - Fix: {suggestion}")
        print()

    if nits:
        print("## 🟡 Suggestions\n")
        for f in nits:
            print(f"- **{f.file}:{f.line}** - {f.message}")
        print()

    if preexisting:
        print("## 🟣 Pre-existing Issues\n")
        for f in preexisting:
            print(f"- **{f.file}:{f.line}** - {f.message}")
        print()

    print("## Summary\n")
    print(f"| Category | Count |")
    print(f"|----------|-------|")
    print(f"| 🔴 Critical | {len(bugs)} |")
    print(f"| 🟡 Suggestions | {len(nits)} |")
    print(f"| 🟣 Pre-existing | {len(preexisting)} |")
    print(f"| **Total** | **{len(findings)}** |")


if __name__ == "__main__":
    sys.exit(main())
