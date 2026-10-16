"""Google Drive integration for Jarvis - secure, read-only access."""

from __future__ import annotations

import json
import os
import pickle
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .config import get_data_dir
from .logging import get_logger
from .tools import Tool, ToolResult

logger = get_logger(__name__)

# OAuth 2.0 scopes for read-only Drive access
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]

# Supported MIME types for content extraction
SUPPORTED_MIME_TYPES = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # Google Docs -> DOCX
    "application/vnd.google-apps.spreadsheet": "text/csv",  # Google Sheets -> CSV
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # Slides -> PPTX
    "text/plain": None,  # Plain text - no conversion needed
    "application/pdf": None,  # PDF - download as-is
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": None,  # DOCX
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": None,  # XLSX
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": None,  # PPTX
}

# Maximum content size for text extraction (100KB)
MAX_CONTENT_SIZE = 100 * 1024

# Google Drive API service name and version
DRIVE_API_SERVICE = "drive"
DRIVE_API_VERSION = "v3"


class GoogleDriveAuth:
    """Handles Google Drive OAuth 2.0 authentication."""

    def __init__(self, client_secrets_path: str = None, token_path: str = None):
        self.data_dir = Path(get_data_dir())
        self.client_secrets_path = client_secrets_path or str(self.data_dir / "google_client_secrets.json")
        self.token_path = token_path or str(self.data_dir / "google_drive_token.json")
        self.credentials: Optional[Credentials] = None
        self.service = None

    def _get_credentials(self) -> Optional[Credentials]:
        """Load or create OAuth credentials."""
        creds = None

        # Load existing token
        if os.path.exists(self.token_path):
            try:
                with open(self.token_path, "r") as f:
                    creds = Credentials.from_authorized_user_info(
                        json.load(f), DRIVE_SCOPES
                    )
            except Exception as e:
                logger.warning(f"Failed to load token: {e}")

        # Refresh or obtain new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self._save_credentials(creds)
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}")
                    creds = None
            else:
                creds = self._get_new_credentials()

        self.credentials = creds
        return creds

    def _get_new_credentials(self) -> Optional[Credentials]:
        """Run the OAuth flow to get new credentials."""
        if not os.path.exists(self.client_secrets_path):
            return None

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                self.client_secrets_path, DRIVE_SCOPES
            )
            # Use localhost with a fixed port for the redirect
            creds = flow.run_local_server(
                port=8080,
                prompt="consent",
                access_type="offline",
                include_granted_scopes="true",
            )
            self._save_credentials(creds)
            return creds
        except Exception as e:
            logger.error(f"OAuth flow failed: {e}")
            return None

    def _save_credentials(self, creds: Credentials) -> None:
        """Save credentials to token file."""
        try:
            with open(self.token_path, "w") as f:
                json.dump(json.loads(creds.to_json()), f, indent=2)
            # Restrict file permissions
            os.chmod(self.token_path, 0o600)
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")

    def get_service(self):
        """Get or create the Google Drive API service."""
        if self.service is None:
            creds = self._get_credentials()
            if not creds:
                return None
            self.service = build(DRIVE_API_SERVICE, DRIVE_API_VERSION, credentials=creds)
        return self.service

    def is_connected(self) -> bool:
        """Check if authenticated and service is available."""
        return self.get_service() is not None

    def disconnect(self) -> bool:
        """Disconnect and remove stored credentials."""
        try:
            if os.path.exists(self.token_path):
                os.remove(self.token_path)
            self.credentials = None
            self.service = None
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect: {e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get connection status information."""
        connected = self.is_connected()
        return {
            "connected": connected,
            "scopes": DRIVE_SCOPES if connected else [],
            "token_file_exists": os.path.exists(self.token_path),
            "client_secrets_exist": os.path.exists(self.client_secrets_path),
        }


class GoogleDriveService:
    """Google Drive API service wrapper for search and retrieval."""

    def __init__(self, auth: GoogleDriveAuth):
        self.auth = auth
        self.service = auth.get_service()

    def _ensure_service(self) -> bool:
        """Ensure service is available."""
        if self.service is None:
            self.service = self.auth.get_service()
        return self.service is not None

    def search_files(
        self,
        query: str,
        max_results: int = 20,
        file_types: Optional[List[str]] = None,
        modified_after: Optional[str] = None,
        order_by: str = "modifiedTime desc",
    ) -> List[Dict[str, Any]]:
        """Search for files in Google Drive."""
        if not self._ensure_service():
            return []

        try:
            # Build query
            query_parts = [query, "trashed = false"]
            if file_types:
                type_queries = " or ".join([f"mimeType = '{mime}'" for mime in file_types])
                if len(file_types) > 1:
                    type_queries = f"({type_queries})"
                query_parts.append(type_queries)
            if modified_after:
                query_parts.append(f"modifiedTime > '{modified_after}'")

            full_query = " and ".join(query_parts)

            results = []
            page_token = None

            while len(results) < 100:  # Hard limit
                page_size = min(50, 100 - len(results))
                response = (
                    self.service.files()
                    .list(
                        q=full_query,
                        pageSize=page_size,
                        fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink, parents)",
                        orderBy=order_by,
                        pageToken=page_token,
                    )
                    .execute()
                )

                files = response.get("files", [])
                for file in files:
                    results.append({
                        "id": file.get("id"),
                        "name": file.get("name"),
                        "mimeType": file.get("mimeType"),
                        "modifiedTime": file.get("modifiedTime"),
                        "size": file.get("size"),
                        "webViewLink": file.get("webViewLink"),
                        "parents": file.get("parents", []),
                    })

                page_token = response.get("nextPageToken")
                if not page_token or len(results) >= max_results:
                    break

            return results[:max_results]

        except HttpError as e:
            logger.error(f"Drive search error: {e}")
            return []
        except Exception as e:
            logger.error(f"Drive search error: {e}")
            return []

    def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed metadata for a file."""
        if not self._ensure_service():
            return None

        try:
            file = (
                self.service.files()
                .get(
                    fileId=file_id,
                    fields="id, name, mimeType, modifiedTime, size, webViewLink, parents, description",
                )
                .execute()
            )
            return {
                "id": file.get("id"),
                "name": file.get("name"),
                "mimeType": file.get("mimeType"),
                "modifiedTime": file.get("modifiedTime"),
                "size": file.get("size"),
                "webViewLink": file.get("webViewLink"),
                "parents": file.get("parents", []),
                "description": file.get("description"),
            }
        except HttpError as e:
            logger.error(f"Get file metadata error: {e}")
            return None

    def get_file_content(
        self,
        file_id: str,
        mime_type: str = None,
        max_size: int = MAX_CONTENT_SIZE,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Get file content as text.
        
        Returns:
            Tuple of (success, content, error_message)
        """
        if not self._ensure_service():
            return False, None, "Not connected to Google Drive"

        try:
            # Get file metadata if mime_type not provided
            if mime_type is None:
                meta = self.get_file_metadata(file_id)
                if not meta:
                    return False, None, "File not found"
                mime_type = meta.get("mimeType", "")

            # Check if MIME type is supported
            if mime_type not in SUPPORTED_MIME_TYPES:
                return False, None, f"Unsupported file type: {mime_type}"

            # Get export/download URL based on MIME type
            export_mime = SUPPORTED_MIME_TYPES.get(mime_type)

            if export_mime is None:
                # Download as-is for supported binary types
                request = self.service.files().get_media(fileId=file_id)
            else:
                # Export Google-native formats
                request = self.service.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )

            # Download with size limit
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            total_size = 0

            while not done:
                status, done = downloader.next_chunk()
                if status:
                    total_size = status.total_size or (status.progress() * status.total_size)
                    if total_size > max_size:
                        return False, None, f"File too large ({total_size} bytes > {max_size})"

            content_bytes = fh.getvalue()

            # Try to decode as text
            try:
                content = content_bytes.decode("utf-8", errors="replace")
            except Exception:
                return False, None, "Failed to decode file as text"

            # Truncate if too long
            if len(content) > max_size:
                content = content[:max_size] + f"... [truncated at {max_size} characters]"

            return True, content, None

        except HttpError as e:
            logger.error(f"Drive file content error: {e}")
            return False, None, f"API error: {e}"
        except Exception as e:
            logger.error(f"File content error: {e}")
            return False, None, str(e)

    def list_files_in_folder(
        self, folder_id: str, max_results: int = 50
    ) -> List[Dict[str, Any]]:
        """List files in a specific folder."""
        if not self._ensure_service():
            return []

        try:
            query = f"'{folder_id}' in parents and trashed = false"
            response = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=max_results,
                    fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            files = response.get("files", [])
            return [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "mimeType": f.get("mimeType"),
                    "modifiedTime": f.get("modifiedTime"),
                    "size": f.get("size"),
                    "webViewLink": f.get("webViewLink"),
                }
                for f in files
            ]
        except HttpError as e:
            logger.error(f"List folder error: {e}")
            return []


# Tool classes for the registry
class DriveConnectTool(Tool):
    name = "drive.connect"
    description = "Connect to Google Drive (OAuth) and return connection status"
    permissions = ["drive.access"]

    def run(self, client_secrets: str = None) -> ToolResult:
        auth = GoogleDriveAuth(client_secrets_path=client_secrets)
        connected = auth.is_connected()
        status = auth.get_status()
        return ToolResult(
            success=connected,
            result=status,
            error="Not connected. Run OAuth flow first." if not connected else None,
        )


class DriveDisconnectTool(Tool):
    name = "drive.disconnect"
    description = "Disconnect from Google Drive and remove stored credentials"
    permissions = ["drive.access"]

    def run(self) -> ToolResult:
        auth = GoogleDriveAuth()
        success = auth.disconnect()
        return ToolResult(
            success=success,
            result={"connected": False},
            error="Disconnect failed" if not success else None,
        )


class DriveStatusTool(Tool):
    name = "drive.status"
    description = "Get Google Drive connection status"
    permissions = ["drive.access"]

    def run(self) -> ToolResult:
        auth = GoogleDriveAuth()
        status = auth.get_status()
        return ToolResult(
            success=True,
            result=status,
        )


class DriveSearchTool(Tool):
    name = "drive.search"
    description = "Search Google Drive files by name, keyword, or filters"
    permissions = ["drive.read"]

    def run(
        self,
        query: str,
        max_results: int = 20,
        file_types: List[str] = None,
        modified_after: str = None,
    ) -> ToolResult:
        auth = GoogleDriveAuth()
        if not auth.is_connected():
            return ToolResult(
                success=False,
                error="Google Drive not connected. Run drive.connect first.",
            )

        service = GoogleDriveService(GoogleDriveAuth())
        results = service.search_files(
            query=query,
            max_results=max_results,
            file_types=file_types,
            modified_after=modified_after,
        )
        return ToolResult(
            success=True,
            result={
                "query": query,
                "count": len(results),
                "files": results,
            },
        )


class DriveGetFileTool(Tool):
    name = "drive.get_file"
    description = "Get file metadata and content by ID"
    permissions = ["drive.read"]

    def run(self, file_id: str, include_content: bool = True) -> ToolResult:
        auth = GoogleDriveAuth()
        if not auth.is_connected():
            return ToolResult(
                success=False,
                error="Google Drive not connected. Run drive.connect first.",
            )

        service = GoogleDriveService(GoogleDriveAuth())
        meta = service.get_file_metadata(file_id)
        if not meta:
            return ToolResult(success=False, error="File not found or inaccessible")

        result = {"metadata": meta}

        if include_content:
            success, content, error = service.get_file_content(file_id)
            if success:
                result["content"] = content
            else:
                result["content_error"] = error

        return ToolResult(success=True, result=result)


class DriveReadFileTool(Tool):
    name = "drive.read"
    description = "Read and extract text content from a Google Drive file"
    permissions = ["drive.read"]

    def run(self, file_id: str) -> ToolResult:
        auth = GoogleDriveAuth()
        if not auth.is_connected():
            return ToolResult(
                success=False,
                error="Google Drive not connected. Run drive.connect first.",
            )

        service = GoogleDriveService(GoogleDriveAuth())
        success, content, error = service.get_file_content(file_id)

        if success:
            return ToolResult(success=True, result={"content": content})
        else:
            return ToolResult(success=False, error=error)


class DriveListFolderTool(Tool):
    name = "drive.list_folder"
    description = "List files in a Google Drive folder"
    permissions = ["drive.read"]

    def run(self, folder_id: str, max_results: int = 50) -> ToolResult:
        auth = GoogleDriveAuth()
        if not auth.is_connected():
            return ToolResult(
                success=False,
                error="Google Drive not connected. Run drive.connect first.",
            )

        service = GoogleDriveService(GoogleDriveAuth())
        files = service.list_files_in_folder(folder_id, max_results)
        return ToolResult(
            success=True,
            result={
                "folder_id": folder_id,
                "count": len(files),
                "files": files,
            },
        )


def get_drive_tools() -> List[Tool]:
    """Get all Google Drive tools for registration."""
    return [
        DriveConnectTool(),
        DriveDisconnectTool(),
        DriveStatusTool(),
        DriveSearchTool(),
        DriveGetFileTool(),
        DriveReadFileTool(),
        DriveListFolderTool(),
    ]


def get_drive_service() -> Optional[GoogleDriveService]:
    """Get a connected Google Drive service instance."""
    auth = GoogleDriveAuth()
    if auth.is_connected():
        return GoogleDriveService(auth)
    return None


def drive_connected() -> bool:
    """Check if Google Drive is connected."""
    auth = GoogleDriveAuth()
    return auth.is_connected()


def drive_status() -> Dict[str, Any]:
    """Get Google Drive connection status."""
    auth = GoogleDriveAuth()
    return auth.get_status()
