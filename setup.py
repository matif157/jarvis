"""Setup script for Jarvis.

Metadata lives here (kept setuptools-58 compatible). The console entry point is
``jarvis``; the web UI ships as package data via ``MANIFEST.in``.
"""

from pathlib import Path

from setuptools import find_packages, setup

ROOT = Path(__file__).resolve().parent


def _read(name: str) -> str:
    path = ROOT / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


setup(
    name="jarvis-assistant",
    version="1.6.1",
    packages=find_packages(exclude=("tests", "tests.*")),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "click>=8.1",
        "rich>=13.0",
        "pydantic>=2.5",
        "python-dotenv>=1.0",
        "httpx>=0.27",
        "fastapi>=0.115",
        "uvicorn[standard]>=0.32",
    ],
    extras_require={
        "dev": ["pytest>=8.0", "build>=1.0"],
    },
    entry_points={
        "console_scripts": [
            "jarvis=jarvis.cli:cli",
        ],
    },
    author="Muhammad Atif",
    license="MIT",
    description="Local-first personal assistant with multi-provider AI, tools, and an Atif Assistant bridge",
    long_description=_read("README.md"),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Console",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Personal Information Manager",
    ],
    project_urls={
        "Source": "https://github.com/matif157/jarvis",
        "Changelog": "https://github.com/matif157/jarvis/blob/main/CHANGELOG.md",
    },
)
