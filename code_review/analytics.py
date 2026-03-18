"""Analytics tracking for code review usage.

Tracks metrics like:
- Number of PRs reviewed
- Number of findings
- Estimated costs
- Per-repo statistics
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ReviewMetrics:
    """Metrics for a single review."""
    pr_number: int
    repo: str
    owner: str
    timestamp: str
    files_changed: int
    lines_added: int
    lines_deleted: int
    findings_count: int
    bugs_count: int
    nits_count: int
    preexisting_count: int
    agents_run: list[str]
    duration_seconds: float
    estimated_cost: float  # Approximate cost based on tokens


class AnalyticsTracker:
    """Tracks and stores analytics for code reviews."""

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            storage_dir = Path.home() / ".code-review-analytics"
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def record_review(self, metrics: ReviewMetrics) -> None:
        """Record metrics from a review."""
        # Save to daily file
        date_str = datetime.now().strftime("%Y-%m-%d")
        daily_file = self.storage_dir / f"reviews_{date_str}.jsonl"

        reviews = []
        if daily_file.exists():
            with open(daily_file) as f:
                reviews = json.load(f)

        reviews.append(metrics.__dict__)
        with open(daily_file, "w") as f:
            json.dump(reviews, f)

        # Update summary
        self._update_summary(metrics)

    def _update_summary(self, metrics: ReviewMetrics) -> None:
        """Update running summary."""
        summary_file = self.storage_dir / "summary.json"

        summary = {
            "total_reviews": 0,
            "total_findings": 0,
            "total_bugs": 0,
            "total_nits": 0,
            "repos": {},
            "estimated_total_cost": 0.0,
        }

        if summary_file.exists():
            with open(summary_file) as f:
                summary = json.load(f)

        # Update totals
        summary["total_reviews"] += 1
        summary["total_findings"] += metrics.findings_count
        summary["total_bugs"] += metrics.bugs_count
        summary["total_nits"] += metrics.nits_count
        summary["estimated_total_cost"] += metrics.estimated_cost

        # Update per-repo stats
        repo_key = f"{metrics.owner}/{metrics.repo}"
        if repo_key not in summary["repos"]:
            summary["repos"][repo_key] = {
                "reviews": 0,
                "findings": 0,
                "bugs": 0,
            }
        summary["repos"][repo_key]["reviews"] += 1
        summary["repos"][repo_key]["findings"] += metrics.findings_count
        summary["repos"][repo_key]["bugs"] += metrics.bugs_count

        with open(summary_file, "w") as f:
            json.dump(summary, f)

    def get_summary(self) -> dict:
        """Get current analytics summary."""
        summary_file = self.storage_dir / "summary.json"

        if not summary_file.exists():
            return {
                "total_reviews": 0,
                "total_findings": 0,
                "total_bugs": 0,
                "total_nits": 0,
                "repos": {},
                "estimated_total_cost": 0.0,
            }

        with open(summary_file) as f:
            return json.load(f)

    def get_repo_stats(self, owner: str, repo: str) -> dict:
        """Get statistics for a specific repo."""
        summary = self.get_summary()
        repo_key = f"{owner}/{repo}"
        return summary.get("repos", {}).get(repo_key, {
            "reviews": 0,
            "findings": 0,
            "bugs": 0,
        })

    def generate_report(self, days: int = 7) -> str:
        """Generate a report for the last N days."""
        from datetime import datetime, timedelta

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        all_reviews = []
        for i in range(days):
            date_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            daily_file = self.storage_dir / f"reviews_{date_str}.jsonl"
            if daily_file.exists():
                with open(daily_file) as f:
                    all_reviews.extend(json.load(f))

        if not all_reviews:
            return "No reviews in the last {days} days."

        # Calculate totals
        total_findings = sum(r["findings_count"] for r in all_reviews)
        total_bugs = sum(r["bugs_count"] for r in all_reviews)
        total_nits = sum(r["nits_count"] for r in all_reviews)
        total_cost = sum(r["estimated_cost"] for r in all_reviews)

        # Group by repo
        repos = {}
        for review in all_reviews:
            repo_key = f"{review['owner']}/{review['repo']}"
            if repo_key not in repos:
                repos[repo_key] = []
            repos[repo_key].append(review)

        report_lines = [
            f"# Code Review Analytics Report",
            f"",
            f"**Period:** Last {days} days ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})",
            f"",
            f"## Summary",
            f"",
            f"| Metric | Value |",
            f"|-------|-------|",
            f"| Total Reviews | {len(all_reviews)} |",
            f"| Total Findings | {total_findings} |",
            f"| 🔴 Bugs | {total_bugs} |",
            f"| 🟡 Nits | {total_nits} |",
            f"| Est. Cost | ${total_cost:.2f} |",
            f"",
            f"## Per Repository",
            f"",
        ]

        for repo_key in sorted(repos.keys()):
            repo_reviews = repos[repo_key]
            report_lines.extend([
                f"### {repo_key}",
                f"",
                f"| Reviews | {len(repo_reviews)} |",
                f"| Findings | {sum(r['findings_count'] for r in repo_reviews)} |",
                f"",
            ])

        return "\n".join(report_lines)
