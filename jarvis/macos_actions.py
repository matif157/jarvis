"""macOS actions adapter for Jarvis - restricted, safe operations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .tools import Tool, ToolResult


# Application allowlist - only these apps can be opened
APP_ALLOWLIST = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "finder": "Finder",
    "notes": "Notes",
    "messages": "Messages",
}

# Valid URL schemes
VALID_URL_SCHEMES = ["http", "https"]

# Default approved directories
APPROVED_DIRS = [
    os.path.expanduser("~/Documents"),
    os.path.expanduser("~/Downloads"),
    os.path.expanduser("~/Desktop"),
]


def _validate_app_name(app_name: str) -> Tuple[bool, Optional[str]]:
    """Validate an application name against the allowlist."""
    normalized = app_name.strip().lower()
    if normalized in APP_ALLOWLIST:
        return True, APP_ALLOWLIST[normalized]
    # Also try exact match
    if app_name in APP_ALLOWLIST.values():
        return True, app_name
    return False, None


def _validate_url(url: str) -> Tuple[bool, Optional[str]]:
    """Validate a URL has an allowed scheme and valid structure."""
    if not url:
        return False, "Empty URL"
    # Parse the scheme
    if "://" not in url:
        return False, "Invalid URL format"
    scheme = url.split("://")[0].lower()
    if scheme not in VALID_URL_SCHEMES:
        return False, f"Invalid scheme: {scheme}. Only http/https allowed."
    # Check for netloc (domain)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.netloc:
            return False, "Invalid URL: missing domain (e.g., example.com)"
    except Exception:
        return False, "Invalid URL format"
    return True, url


def _validate_path_safe(path: str, approved_dirs: List[str] = None) -> Tuple[bool, Optional[str]]:
    """Validate a path is within approved directories."""
    if approved_dirs is None:
        approved_dirs = APPROVED_DIRS
    try:
        abs_path = os.path.abspath(path)
        p = os.path.realpath(abs_path)
        for approved_dir in approved_dirs:
            abs_appdir = os.path.abspath(approved_dir)
            ad_real = os.path.realpath(abs_appdir)
            # Allow if path starts with approved dir or is the approved dir itself
            if p == ad_real or p.startswith(ad_real + os.sep):
                return True, p
        return False, f"Path not in approved directories: {path}"
    except Exception as e:
        return False, str(e)


def _open_app(app_name: str) -> ToolResult:
    """Open an approved application using osascript."""
    valid, resolved_name = _validate_app_name(app_name)
    if not valid:
        return ToolResult(
            success=False,
            error=f"Application not in allowlist: {app_name}",
        )
    
    try:
        # Use osascript to launch the application
        script = f'tell application "{resolved_name}" to activate'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return ToolResult(
                success=True,
                result={"app": resolved_name, "action": "activate"},
            )
        else:
            return ToolResult(
                success=False,
                error=f"Failed to activate application: {result.stderr.strip()}",
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Error opening application: {str(e)}",
        )


def _open_url(url: str) -> ToolResult:
    """Open a URL in the default browser using osascript."""
    valid, validated_url = _validate_url(url)
    if not valid:
        return ToolResult(
            success=False,
            error=f"Invalid scheme: {url.split('://')[0].lower() if '://' in url else ''}. Only http/https allowed.",
        )
    
    try:
        # Use osascript to open the URL in the default browser
        script = f'tell application "Finder" to open location "{validated_url}"'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return ToolResult(
                success=True,
                result={"url": validated_url, "action": "open"},
            )
        else:
            return ToolResult(
                success=False,
                error=f"Failed to open URL: {result.stderr.strip()}",
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Error opening URL: {str(e)}",
        )


def _reveal_in_finder(file_path: str) -> ToolResult:
    """Reveal a file in Finder using osascript."""
    valid, validated_path = _validate_path_safe(file_path)
    if not valid:
        return ToolResult(
            success=False,
            error=f"Path not in approved directories: {file_path}",
        )
    
    try:
        # Use osascript to reveal the file in Finder
        script = f'tell application "Finder" to reveal POSIX file "{validated_path}"'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return ToolResult(
                success=True,
                result={"path": validated_path, "action": "reveal"},
            )
        else:
            return ToolResult(
                success=False,
                error=f"Failed to reveal in Finder: {result.stderr.strip()}",
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Error revealing in Finder: {str(e)}",
        )


def _create_file(filename: str, content: str, directory: str = None) -> ToolResult:
    """Create a new file in an approved directory."""
    # Validate directory
    if directory is None:
        directory = os.getcwd()
    valid, validated_dir = _validate_path_safe(directory)
    if not valid:
        return ToolResult(
            success=False,
            error=f"Path not in approved directories: {directory}",
        )
    
    # Validate filename - reject traversal sequences
    if ".." in filename or filename.startswith("/"):
        return ToolResult(
            success=False,
            error="Invalid filename: path traversal detected",
        )
    
    # Clean the filename
    safe_filename = os.path.basename(filename)
    if not safe_filename:
        return ToolResult(
            success=False,
            error="Invalid filename: empty after sanitization",
        )
    
    full_path = os.path.join(validated_dir, safe_filename)
    
    # Check if file already exists
    if os.path.exists(full_path):
        return ToolResult(
            success=False,
            error=f"File already exists: {full_path}",
            meta={"suggested_action": "Ask user whether to replace or choose another name"},
        )
    
    # Write the file
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Verify the file was created
        if os.path.exists(full_path):
            # Read back the content to verify
            with open(full_path, "r", encoding="utf-8") as f:
                actual_content = f.read()
            
            return ToolResult(
                success=True,
                result={
                    "path": full_path,
                    "filename": safe_filename,
                    "content": actual_content,
                },
            )
        else:
            return ToolResult(
                success=False,
                error="File was not created after write attempt",
            )
    except Exception as e:
        return ToolResult(
            success=False,
            error=f"Error creating file: {str(e)}",
        )


# Tool classes for the registry
class OpenAppTool(Tool):
    name = "app.open"
    description = "Open an approved macOS application"
    permissions = ["app.open"]
    
    def run(self, app_name: str) -> ToolResult:
        return _open_app(app_name)


class OpenURLTool(Tool):
    name = "url.open"
    description = "Open a valid HTTP or HTTPS URL in the browser"
    permissions = ["web.search"]
    
    def run(self, url: str) -> ToolResult:
        return _open_url(url)


class RevealInFinderTool(Tool):
    name = "finder.reveal"
    description = "Reveal a file in Finder"
    permissions = ["file.read"]
    
    def run(self, file_path: str) -> ToolResult:
        return _reveal_in_finder(file_path)


class CreateFileTool(Tool):
    name = "file.create"
    description = "Create a new file in an approved directory"
    permissions = ["file.write"]
    
    def run(self, filename: str, content: str = "", directory: str = None) -> ToolResult:
        return _create_file(filename, content, directory)
