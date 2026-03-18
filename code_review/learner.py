"""Learning module - learns from codebase patterns and user preferences."""

import json
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Pattern:
    """A learned code pattern."""
    name: str
    description: str
    examples: list[str] = field(default_factory=list)
    occurrences: int = 0
    last_seen: str = ""


@dataclass
class UserPreference:
    """A learned user preference."""
    category: str
    rule: str
    accepted_count: int = 0
    rejected_count: int = 0
    confidence: float = 0.5


class Learner:
    """Learns from codebase patterns and user feedback."""

    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            storage_dir = Path.home() / ".code-review-learner"
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.patterns: dict[str, Pattern] = {}
        self.preferences: dict[str, UserPreference] = {}
        self.project_rules: dict[str, list[str]] = {}

        self._load_state()

    def _load_state(self) -> None:
        """Load learned state from disk."""
        patterns_file = self.storage_dir / "patterns.json"
        if patterns_file.exists():
            with open(patterns_file) as f:
                data = json.load(f)
                self.patterns = {
                    k: Pattern(**v) for k, v in data.get("patterns", {}).items()
                }

        preferences_file = self.storage_dir / "preferences.json"
        if preferences_file.exists():
            with open(preferences_file) as f:
                data = json.load(f)
                self.preferences = {
                    k: UserPreference(**v) for k, v in data.get("preferences", {}).items()
                }

        rules_file = self.storage_dir / "project_rules.json"
        if rules_file.exists():
            with open(rules_file) as f:
                self.project_rules = json.load(f)

    def _save_state(self) -> None:
        """Save learned state to disk."""
        patterns_file = self.storage_dir / "patterns.json"
        with open(patterns_file, "w") as f:
            json.dump({
                "patterns": {
                    k: {"name": v.name, "description": v.description,
                        "examples": v.examples, "occurrences": v.occurrences,
                        "last_seen": v.last_seen}
                    for k, v in self.patterns.items()
                }
            }, f, indent=2)

        preferences_file = self.storage_dir / "preferences.json"
        with open(preferences_file, "w") as f:
            json.dump({
                "preferences": {
                    k: {"category": v.category, "rule": v.rule,
                        "accepted_count": v.accepted_count,
                        "rejected_count": v.rejected_count,
                        "confidence": v.confidence}
                    for k, v in self.preferences.items()
                }
            }, f, indent=2)

        rules_file = self.storage_dir / "project_rules.json"
        with open(rules_file, "w") as f:
            json.dump(self.project_rules, f, indent=2)

    def analyze_codebase(self, files: dict[str, str]) -> dict:
        """Analyze codebase to learn patterns."""
        patterns_found = {
            "naming_conventions": {},
            "import_patterns": {},
            "error_handling": {},
            "logging": {},
            "testing": {},
        }

        for filepath, content in files.items():
            # Learn naming conventions
            self._learn_naming_conventions(filepath, content, patterns_found)

            # Learn import patterns
            self._learn_import_patterns(filepath, content, patterns_found)

            # Learn error handling patterns
            self._learn_error_handling(filepath, content, patterns_found)

            # Learn logging patterns
            self._learn_logging_patterns(filepath, content, patterns_found)

        # Store learned patterns
        for category, patterns in patterns_found.items():
            for pattern_name, examples in patterns.items():
                key = f"{category}:{pattern_name}"
                if key in self.patterns:
                    self.patterns[key].examples.extend(examples[:5])
                    self.patterns[key].occurrences += len(examples)
                    self.patterns[key].last_seen = datetime.now().isoformat()
                else:
                    self.patterns[key] = Pattern(
                        name=pattern_name,
                        description=f"Learned {category} pattern",
                        examples=examples[:10],
                        occurrences=len(examples),
                        last_seen=datetime.now().isoformat(),
                    )

        self._save_state()
        return patterns_found

    def _learn_naming_conventions(self, filepath: str, content: str, patterns: dict) -> None:
        """Learn naming conventions from code."""
        import re

        # Learn function naming
        functions = re.findall(r'def\s+(\w+)\s*\(', content)
        for func in functions:
            if func.startswith('_'):
                style = 'private_snake_case'
            elif '_' in func:
                style = 'snake_case'
            else:
                style = 'camelCase'

            key = f"function:{style}"
            if key not in patterns["naming_conventions"]:
                patterns["naming_conventions"][key] = []
            patterns["naming_conventions"][key].append(f"{filepath}:{func}")

        # Learn variable naming
        variables = re.findall(r'(\w+)\s*=', content)
        for var in variables[:20]:  # Limit to avoid noise
            if var.isupper():
                style = 'UPPER_CASE'
            elif var[0].isupper():
                style = 'PascalCase'
            elif '_' in var:
                style = 'snake_case'
            else:
                style = 'camelCase'

            key = f"variable:{style}"
            if key not in patterns["naming_conventions"]:
                patterns["naming_conventions"][key] = []
            patterns["naming_conventions"][key].append(f"{filepath}:{var}")

    def _learn_import_patterns(self, filepath: str, content: str, patterns: dict) -> None:
        """Learn import patterns."""
        import re

        # Learn import grouping
        imports = re.findall(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', content, re.MULTILINE)
        for module, names in imports:
            if module:
                key = f"from_import:{module}"
            else:
                key = f"direct_import"

            if key not in patterns["import_patterns"]:
                patterns["import_patterns"][key] = []
            patterns["import_patterns"][key].append(f"{filepath}")

    def _learn_error_handling(self, filepath: str, content: str, patterns: dict) -> None:
        """Learn error handling patterns."""
        import re

        # Learn try-except patterns
        try_blocks = re.findall(r'try:(.*?)except\s+(\w+)', content, re.DOTALL)
        for block, exception in try_blocks:
            key = f"exception:{exception}"
            if key not in patterns["error_handling"]:
                patterns["error_handling"][key] = []
            patterns["error_handling"][key].append(filepath)

    def _learn_logging_patterns(self, filepath: str, content: str, patterns: dict) -> None:
        """Learn logging patterns."""
        import re

        # Learn logging usage
        log_calls = re.findall(r'(logger|console|log)\.(debug|info|warn|error|log)', content)
        for logger, level in log_calls:
            key = f"log_level:{level}"
            if key not in patterns["logging"]:
                patterns["logging"][key] = []
            patterns["logging"][key].append(filepath)

    def record_feedback(self, finding_id: str, accepted: bool, category: str = "general") -> None:
        """Record user feedback on a finding."""
        key = f"{category}:{finding_id}"

        if key in self.preferences:
            if accepted:
                self.preferences[key].accepted_count += 1
            else:
                self.preferences[key].rejected_count += 1

            total = self.preferences[key].accepted_count + self.preferences[key].rejected_count
            self.preferences[key].confidence = self.preferences[key].accepted_count / total
        else:
            self.preferences[key] = UserPreference(
                category=category,
                rule=finding_id,
                accepted_count=1 if accepted else 0,
                rejected_count=0 if accepted else 1,
                confidence=1.0 if accepted else 0.0,
            )

        self._save_state()

    def should_report(self, finding_type: str, category: str = "general") -> tuple[bool, float]:
        """Determine if a finding should be reported based on learned preferences.

        Returns:
            tuple[bool, float]: (should_report, confidence) where should_report
            indicates if the finding should be displayed and confidence is the
            learned confidence level (0.0 to 1.0).
        """
        key = f"{category}:{finding_type}"

        if key in self.preferences:
            pref = self.preferences[key]
            # Only skip if user has consistently rejected this type
            if pref.rejected_count > 5 and pref.confidence < 0.2:
                return (False, pref.confidence)

        return (True, 1.0)

    def get_project_rules(self, project_id: str) -> list[str]:
        """Get learned rules for a specific project."""
        return self.project_rules.get(project_id, [])

    def set_project_rule(self, project_id: str, rule: str) -> None:
        """Set a rule for a specific project."""
        if project_id not in self.project_rules:
            self.project_rules[project_id] = []
        if rule not in self.project_rules[project_id]:
            self.project_rules[project_id].append(rule)
            self._save_state()

    def get_learned_patterns_summary(self) -> dict:
        """Get summary of learned patterns."""
        return {
            "total_patterns": len(self.patterns),
            "total_preferences": len(self.preferences),
            "top_patterns": sorted(
                [(p.name, p.occurrences) for p in self.patterns.values()],
                key=lambda x: x[1],
                reverse=True
            )[:10],
            "confidence_rules": [
                (p.rule, p.confidence)
                for p in self.preferences.values()
                if p.accepted_count + p.rejected_count >= 3
            ],
        }
