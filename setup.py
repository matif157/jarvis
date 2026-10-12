"""Setup script for Jarvis"""

from setuptools import setup, find_packages

setup(
    name="jarvis-assistant",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click",
        "rich",
        "pydantic",
        "python-dotenv",
    ],
    entry_points={
        "console_scripts": [
            "jarvis=jarvis.cli:cli",
        ],
    },
    author="Muhammad Atif",
    description="Local-first personal assistant",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
)
