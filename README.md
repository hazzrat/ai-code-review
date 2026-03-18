# AI Code Review Tool

A multi-agent AI-powered code review system that analyzes pull requests and provides comprehensive feedback.

## Features

- **13 Specialized Agents**: Each agent focuses on a specific aspect of code quality
  - Logic & Correctness
  - Security Vulnerabilities
  - Edge Cases & Error Handling
  - Type Safety
  - Regression Detection
  - Architecture & Design
  - Performance
  - Documentation
  - Testing
  - Accessibility
  - Database Operations
  - React/TypeScript Patterns
  - CLAUDE.md Compliance

- **Parallel Execution**: Agents run concurrently for fast reviews
- **Learning System**: Persists patterns and improves over time
- **Context Analysis**: Builds dependency graphs for better understanding
- **Auto-Resolution**: Automatically resolves fixed issues on PR updates

## Installation

```bash
pip install -e .
```

Or install dependencies directly:

```bash
pip install -r requirements.txt
```

## Configuration

Set your API key:

```bash
export CODE_REVIEW_API_KEY="your-api-key"
```

Or use one of these environment variables (checked in order):
- `CODE_REVIEW_API_KEY`
- `ANTHROPIC_API_KEY`
- `CLAUDE_API_KEY`

Create a `config.yaml` file (optional):

```yaml
api:
  endpoint: "https://api.z.ai/api/anthropic"
  model: "glm-5"
  max_tokens: 4096

review:
  min_agents: 3
  max_agents: 6
  severity_threshold: "nit"
  max_diff_size: 100000

agents:
  - name: logic
    enabled: true
  - name: security
    enabled: true
  # ... other agents

verification:
  enabled: true
  confidence_threshold: 0.7

output:
  post_comments: true
  verbose: false
```

## Usage

### Review Current Directory

```bash
python -m code_review
```

### Review a Pull Request

```bash
python -m code_review --pr https://github.com/owner/repo/pull/123
```

### Review Only Changes (Diff Mode)

```bash
python -m code_review --diff
```

### Run Specific Agents

```bash
python -m code_review --agents security,logic,types
```

### Enable Learning Mode

```bash
python -m code_review --learn
```

### Verbose Output

```bash
python -m code_review --verbose
```

### Output Formats

```bash
# GitHub PR comments (requires --pr)
python -m code_review --pr https://github.com/owner/repo/pull/123 --format github

# JSON output
python -m code_review --format json

# Plain text (default)
python -m code_review --format text
```

## CLAUDE.md Integration

The tool reads `CLAUDE.md` files from your repository to understand project-specific guidelines. It checks:
1. New code violations against CLAUDE.md rules
2. Changes that make CLAUDE.md statements outdated

Place a `CLAUDE.md` file in your repository root with your coding standards.

## Learning System

The learning module persists patterns in `~/.code-review-learner/`:
- Patterns to avoid
- Common fixes
- Project-specific knowledge

Enable learning mode with `--learn` to contribute to this knowledge base.

## Development

### Project Structure

```
ai-code-review/
├── code_review/
│   ├── agents/           # Specialized review agents
│   │   ├── base.py       # Base agent class
│   │   ├── logic.py      # Logic & correctness
│   │   ├── security.py   # Security vulnerabilities
│   │   └── ...           # Other agents
│   ├── __init__.py
│   ├── __main__.py       # Entry point
│   ├── aggregator.py     # Finding aggregation
│   ├── analytics.py      # Usage analytics
│   ├── auto_resolve.py   # Auto-resolution logic
│   ├── cli.py            # Command-line interface
│   ├── config.py         # Configuration management
│   ├── context_analyzer.py  # Dependency analysis
│   ├── fetcher.py        # PR/diff fetching
│   ├── learner.py        # Learning system
│   ├── orchestrator.py   # Agent orchestration
│   └── poster.py         # GitHub posting
├── prompts/              # Agent prompt templates
├── config.yaml           # Default configuration
├── requirements.txt      # Python dependencies
└── setup.py              # Package setup
```

### Adding a New Agent

1. Create a new file in `code_review/agents/`
2. Extend the `BaseAgent` class
3. Implement the `analyze()` method
4. Register in `code_review/orchestrator.py`
5. Add prompt template in `prompts/`

## License

MIT License
