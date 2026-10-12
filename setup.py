"""Setup script for Jarvis."""

from setuptools import find_packages, setup

setup(
    name="jarvis-assistant",
    version="0.2.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click",
        "rich",
        "pydantic",
        "python-dotenv",
        "httpx",
        "fastapi",
        "uvicorn[standard]",
    ],
    entry_points={
        "console_scripts": [
            "jarvis=jarvis.cli:cli",
        ],
    },
    author="Muhammad Atif",
    description="Local-first personal assistant with multi-provider AI and Atif Assistant bridge",
    python_requires=">=3.9",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)
