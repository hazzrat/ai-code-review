"""Setup for code-review package."""

from setuptools import setup, find_packages

setup(
    name="code-review",
    version="0.1.0",
    description="Multi-agent AI code review system",
    author="Your Name",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28.0",
        "pyyaml>=6.0",
        "aiohttp>=3.8.0",
        "tenacity>=8.0.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "code-review=code_review.cli:main",
        ],
    },
    python_requires=">=3.9",
)
