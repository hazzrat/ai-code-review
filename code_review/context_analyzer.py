"""Context analyzer - understands file relationships and dependencies."""

import os
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class FileNode:
    """Represents a file in the dependency graph."""
    path: str
    imports: list[str] = field(default_factory=list)
    imported_by: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    is_entry_point: bool = False
    file_type: str = ""


@dataclass
class DependencyGraph:
    """Dependency graph for the codebase."""
    files: dict[str, FileNode] = field(default_factory=dict)
    modules: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


class ContextAnalyzer:
    """Analyzes codebase structure and relationships."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self.graph = DependencyGraph()

    def build_context(self, files: dict[str, str]) -> dict:
        """Build context for all files in the codebase."""
        # First pass: identify all files
        for filepath, content in files.items():
            node = FileNode(
                path=filepath,
                file_type=self._get_file_type(filepath),
                is_entry_point=self._is_entry_point(filepath),
            )
            self.graph.files[filepath] = node

        # Second pass: analyze imports/exports
        for filepath, content in files.items():
            self._analyze_imports(filepath, content)
            self._analyze_exports(filepath, content)

        # Third pass: build reverse dependencies
        for filepath, node in self.graph.files.items():
            for imp in node.imports:
                resolved = self._resolve_import(imp, filepath)
                if resolved and resolved in self.graph.files:
                    self.graph.files[resolved].imported_by.append(filepath)

        return self._build_context_map()

    def _get_file_type(self, filepath: str) -> str:
        """Determine file type from extension."""
        ext = Path(filepath).suffix.lower()
        types = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'react',
            '.ts': 'typescript',
            '.tsx': 'react-typescript',
            '.sql': 'sql',
            '.yaml': 'config',
            '.yml': 'config',
            '.json': 'config',
            '.md': 'documentation',
        }
        return types.get(ext, 'unknown')

    def _is_entry_point(self, filepath: str) -> bool:
        """Check if file is an entry point."""
        entry_points = {
            'main.py', 'app.py', 'index.js', 'index.ts', 'index.tsx',
            '__init__.py', '__main__.py', 'server.js', 'server.ts',
        }
        return Path(filepath).name in entry_points

    def _analyze_imports(self, filepath: str, content: str) -> None:
        """Extract imports from file."""
        node = self.graph.files.get(filepath)
        if not node:
            return

        if node.file_type in ('python',):
            # Python imports
            patterns = [
                r'^import\s+(\S+)',
                r'^from\s+(\S+)\s+import',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content, re.MULTILINE)
                node.imports.extend(matches)

        elif node.file_type in ('javascript', 'react', 'typescript', 'react-typescript'):
            # JavaScript/TypeScript imports
            patterns = [
                r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]',
                r'require\([\'"]([^\'"]+)[\'"]\)',
                r'import\s*\([\'"]([^\'"]+)[\'"]\)',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content)
                node.imports.extend(matches)

    def _analyze_exports(self, filepath: str, content: str) -> None:
        """Extract exports from file."""
        node = self.graph.files.get(filepath)
        if not node:
            return

        if node.file_type in ('python',):
            # Python exports (classes and functions)
            patterns = [
                r'^class\s+(\w+)',
                r'^def\s+(\w+)',
                r'^(\w+)\s*=',  # Top-level variables
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content, re.MULTILINE)
                node.exports.extend(matches)

        elif node.file_type in ('javascript', 'react', 'typescript', 'react-typescript'):
            # JavaScript/TypeScript exports
            patterns = [
                r'export\s+(?:default\s+)?(?:class|function|const|let|var)\s+(\w+)',
                r'export\s*{\s*([^}]+)\s*}',
            ]
            for pattern in patterns:
                matches = re.findall(pattern, content)
                if matches:
                    for match in matches:
                        if ',' in match:
                            node.exports.extend([m.strip() for m in match.split(',')])
                        else:
                            node.exports.append(match)

    def _resolve_import(self, import_path: str, from_file: str) -> Optional[str]:
        """Resolve an import to a file path."""
        # Handle relative imports
        if import_path.startswith('.'):
            base_dir = Path(from_file).parent
            resolved = (base_dir / import_path.replace('.', '').replace('/', os.sep))

            # Try common extensions
            for ext in ['.py', '.js', '.ts', '.tsx', '.jsx']:
                test_path = str(resolved) + ext
                if test_path in self.graph.files:
                    return test_path
                test_path = str(resolved / '__init__') + ext
                if test_path in self.graph.files:
                    return test_path

        # Handle absolute imports
        for filepath in self.graph.files:
            if filepath.replace('/', '.').endswith(import_path):
                return filepath
            if filepath.endswith(import_path.replace('.', '/') + '.py'):
                return filepath
            if filepath.endswith(import_path + '.ts'):
                return filepath
            if filepath.endswith(import_path + '.tsx'):
                return filepath

        return None

    def _build_context_map(self) -> dict:
        """Build context map for code review."""
        context_map = {
            "entry_points": [],
            "core_modules": [],
            "utility_modules": [],
            "test_files": [],
            "dependencies": {},
            "reverse_dependencies": {},
            "module_groups": {},
        }

        # Identify module groups
        for filepath in self.graph.files:
            parts = Path(filepath).parts
            if len(parts) > 1:
                module = parts[0]
                if module not in context_map["module_groups"]:
                    context_map["module_groups"][module] = []
                context_map["module_groups"][module].append(filepath)

        # Categorize files
        for filepath, node in self.graph.files.items():
            if node.is_entry_point:
                context_map["entry_points"].append(filepath)
            elif 'test' in filepath.lower() or 'spec' in filepath.lower():
                context_map["test_files"].append(filepath)
            elif len(node.imported_by) > 3:
                context_map["core_modules"].append(filepath)
            elif len(node.imports) > 0 and len(node.imported_by) == 0:
                context_map["utility_modules"].append(filepath)

            # Store dependencies
            context_map["dependencies"][filepath] = node.imports
            context_map["reverse_dependencies"][filepath] = node.imported_by

        return context_map

    def get_related_files(self, filepath: str, depth: int = 2) -> list[str]:
        """Get files related to the given file (imports and imported by)."""
        related = set()

        def traverse(path: str, current_depth: int):
            if current_depth > depth:
                return

            node = self.graph.files.get(path)
            if not node:
                return

            for imp in node.imports:
                resolved = self._resolve_import(imp, path)
                if resolved and resolved not in related:
                    related.add(resolved)
                    traverse(resolved, current_depth + 1)

            for by in node.imported_by:
                if by not in related:
                    related.add(by)
                    traverse(by, current_depth + 1)

        traverse(filepath, 0)
        return list(related)

    def get_file_context(self, filepath: str, files: dict[str, str]) -> dict[str, str]:
        """Get content of related files for context."""
        related = self.get_related_files(filepath)
        return {
            path: files[path]
            for path in related
            if path in files and len(files.get(path, '')) < 50000  # Limit file size
        }

    def detect_patterns(self, files: dict[str, str]) -> dict:
        """Detect architectural patterns in the codebase."""
        patterns = {
            "api_routes": [],
            "database_models": [],
            "services": [],
            "controllers": [],
            "middleware": [],
            "utils": [],
            "components": [],
            "hooks": [],
        }

        for filepath, content in files.items():
            # Detect API routes
            if re.search(r'@\w+\.route|router\.(get|post|put|delete)|app\.(get|post)', content):
                patterns["api_routes"].append(filepath)

            # Detect database models
            if re.search(r'class\s+\w+\(.*Model|SQLAlchemy|mongoose\.Schema|prisma', content):
                patterns["database_models"].append(filepath)

            # Detect services
            if re.search(r'class\s+\w+Service|def\s+\w+_service', content, re.IGNORECASE):
                patterns["services"].append(filepath)

            # Detect controllers
            if re.search(r'class\s+\w+Controller', content):
                patterns["controllers"].append(filepath)

            # Detect middleware
            if re.search(r'@.*middleware|def\s+middleware|use\(', content):
                patterns["middleware"].append(filepath)

            # Detect React components
            if re.search(r'(function|const)\s+\w+\s*=\s*\(|export\s+default\s+function', content):
                if filepath.endswith(('.jsx', '.tsx')):
                    patterns["components"].append(filepath)

            # Detect React hooks
            if re.search(r'use[A-Z]\w+', content):
                patterns["hooks"].append(filepath)

        return patterns
