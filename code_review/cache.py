"""Finding cache for deterministic results.

Caches findings by file content hash to ensure consistent results
for the same input across multiple runs.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class CachedFinding:
    """A cached finding with metadata."""
    file: str
    line: int
    message: str
    severity: str
    reasoning: str = ""
    agent: str = ""
    confidence: float = 1.0
    suggestion: str = ""
    timestamp: float = field(default_factory=time.time)
    pass_count: int = 1  # Number of passes that found this
    consensus_score: float = 1.0  # Fraction of passes that found this


@dataclass
class CacheEntry:
    """Cache entry for a file."""
    file_hash: str
    findings: list[CachedFinding]
    timestamp: float
    agent_name: str


class FindingCache:
    """Cache for code review findings.

    Uses file content hashes to ensure deterministic results.
    Same file content always produces the same cached findings.
    """

    def __init__(self, cache_dir: Optional[Path] = None, ttl_hours: int = 24):
        self.cache_dir = cache_dir or Path.home() / ".code-review-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_hours * 3600
        self._memory_cache: dict[str, CacheEntry] = {}

    def _compute_hash(self, content: str, agent_name: str) -> str:
        """Compute a hash for file content and agent combination."""
        combined = f"{agent_name}:{content}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _get_cache_path(self, file_hash: str) -> Path:
        """Get the cache file path for a hash."""
        return self.cache_dir / f"{file_hash}.json"

    def get(self, key: str, agent_name: Optional[str] = None) -> Optional[list[CachedFinding]]:
        """Get cached findings for a key or content.

        Args:
            key: Either a pre-computed cache key or content string
            agent_name: Agent name (only needed if key is content string)

        Returns:
            Cached findings or None if not found/expired
        """
        # If agent_name provided, treat key as content and compute hash
        if agent_name:
            file_hash = self._compute_hash(key, agent_name)
        else:
            file_hash = key

        # Check memory cache first
        if file_hash in self._memory_cache:
            entry = self._memory_cache[file_hash]
            if time.time() - entry.timestamp < self.ttl_seconds:
                return entry.findings

        # Check disk cache
        cache_path = self._get_cache_path(file_hash)
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    data = json.load(f)

                entry = CacheEntry(
                    file_hash=data["file_hash"],
                    findings=[CachedFinding(**f) for f in data["findings"]],
                    timestamp=data["timestamp"],
                    agent_name=data["agent_name"],
                )

                # Check TTL
                if time.time() - entry.timestamp < self.ttl_seconds:
                    self._memory_cache[file_hash] = entry
                    return entry.findings
            except (json.JSONDecodeError, KeyError):
                pass

        return None

    def set(self, key: str, findings: list, agent_name: str = "unknown") -> None:
        """Cache findings for a key.

        Args:
            key: Cache key (or content string)
            findings: List of findings to cache (can be CachedFinding or ConsensusFinding)
            agent_name: Agent name
        """
        # Handle both CachedFinding and ConsensusFinding objects
        cached_findings = []
        for f in findings:
            if isinstance(f, CachedFinding):
                cached_findings.append(f)
            elif hasattr(f, 'finding'):
                # ConsensusFinding object
                cf = CachedFinding(
                    file=f.finding.file,
                    line=f.finding.line,
                    message=f.finding.message,
                    severity=f.finding.severity,
                    reasoning=f.finding.reasoning,
                    agent=f.finding.agent,
                    confidence=f.consensus_score,
                    pass_count=f.pass_count,
                    consensus_score=f.consensus_score,
                )
                cached_findings.append(cf)
            elif hasattr(f, 'file'):
                # Finding object
                cf = CachedFinding(
                    file=f.file,
                    line=f.line,
                    message=f.message,
                    severity=f.severity,
                    reasoning=getattr(f, 'reasoning', ''),
                    agent=getattr(f, 'agent', ''),
                    confidence=getattr(f, 'confidence', 1.0),
                )
                cached_findings.append(cf)

        # Use key directly if it looks like a hash, otherwise compute hash
        if len(key) == 16 and all(c in '0123456789abcdef' for c in key):
            file_hash = key
        else:
            file_hash = self._compute_hash(key, agent_name)

        entry = CacheEntry(
            file_hash=file_hash,
            findings=cached_findings,
            timestamp=time.time(),
            agent_name=agent_name,
        )

        # Store in memory
        self._memory_cache[file_hash] = entry

        # Store on disk
        cache_path = self._get_cache_path(file_hash)
        data = {
            "file_hash": file_hash,
            "findings": [f.__dict__ for f in cached_findings],
            "timestamp": entry.timestamp,
            "agent_name": agent_name,
        }
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)

    def clear_expired(self) -> int:
        """Clear expired cache entries. Returns number cleared."""
        cleared = 0
        now = time.time()

        # Clear memory cache
        expired_keys = [
            k for k, v in self._memory_cache.items()
            if now - v.timestamp >= self.ttl_seconds
        ]
        for key in expired_keys:
            del self._memory_cache[key]
            cleared += 1

        # Clear disk cache
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file) as f:
                    data = json.load(f)
                if now - data.get("timestamp", 0) >= self.ttl_seconds:
                    cache_file.unlink()
                    cleared += 1
            except (json.JSONDecodeError, KeyError):
                cache_file.unlink()
                cleared += 1

        return cleared

    def clear_all(self) -> None:
        """Clear all cache entries."""
        self._memory_cache.clear()
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
