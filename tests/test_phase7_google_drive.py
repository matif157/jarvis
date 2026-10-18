"""Phase 7 Google Drive Integration Tests"""


from jarvis.google_drive import (
    DriveConnectTool,
    DriveDisconnectTool,
    DriveGetFileTool,
    DriveListFolderTool,
    DriveReadFileTool,
    DriveSearchTool,
    DriveStatusTool,
    GoogleDriveAuth,
    GoogleDriveService,
    drive_connected,
    drive_status,
    get_drive_tools,
)


def test_drive_tools_registered():
    """Test that all Drive tools are registered."""
    tools = get_drive_tools()
    names = [t.name for t in tools]
    expected = [
        "drive.connect",
        "drive.disconnect",
        "drive.status",
        "drive.search",
        "drive.get_file",
        "drive.read",
        "drive.list_folder",
    ]
    for name in expected:
        assert name in names, f"Missing tool: {name}"
    print("✓ Test 1 PASSED: All Drive tools registered")


def test_drive_auth_initialization():
    """Test GoogleDriveAuth initialization."""
    auth = GoogleDriveAuth()
    assert auth.client_secrets_path is not None
    assert auth.token_path is not None
    assert auth.credentials is None
    assert auth.service is None
    print("✓ Test 1 PASSED: DriveAuth initialization")


def test_drive_connected_false_initially():
    """Test that drive is not connected initially."""
    connected = drive_connected()
    assert connected is False
    print("✓ Test 2 PASSED: Drive not connected initially")


def test_drive_status_structure():
    """Test drive_status returns correct structure."""
    status = drive_status()
    assert "connected" in status
    assert "scopes" in status
    assert "token_file_exists" in status
    assert "client_secrets_exist" in status
    assert status["connected"] is False
    print("✓ Test 3 PASSED: Drive status structure")


def test_drive_auth_credentials_none_initially():
    """Test that credentials are None initially."""
    auth = GoogleDriveAuth()
    assert auth.credentials is None
    assert auth.service is None
    print("✓ Test 4 PASSED: Auth credentials None initially")


def test_drive_status_fields():
    """Test drive status returns expected fields."""
    auth = GoogleDriveAuth()
    status = auth.get_status()
    assert isinstance(status, dict)
    assert "connected" in status
    assert "scopes" in status
    assert "token_file_exists" in status
    assert "client_secrets_exist" in status
    print("✓ Test 3b PASSED: Drive status fields")


def test_drive_connect_tool_not_connected():
    """Test drive.connect tool when not connected."""
    tool = DriveConnectTool()
    r = tool.run()
    assert r.success is False
    assert "Not connected" in r.error or "OAuth" in r.error or "credentials" in r.error.lower()
    print("✓ Test 5 PASSED: Connect tool when not connected")


def test_drive_disconnect_tool():
    """Test drive.disconnect tool."""
    tool = DriveDisconnectTool()
    r = tool.run()
    assert r.success is True
    assert r.result.get("connected") is False
    print("✓ Test 4 PASSED: Drive disconnect tool")


def test_drive_status_tool():
    """Test drive.status tool."""
    tool = DriveStatusTool()
    r = tool.run()
    assert r.success is True
    assert "connected" in r.result
    assert r.result["connected"] is False
    print("✓ Test 5 PASSED: Drive status tool")


def test_drive_search_tool_not_connected():
    """Test drive.search tool when not connected."""
    tool = DriveSearchTool()
    r = tool.run(query="test")
    assert r.success is False
    assert "not connected" in r.error.lower() or "connect" in r.error.lower()
    print("✓ Test 6 PASSED: Search tool when not connected")


def test_drive_get_file_tool_not_connected():
    """Test drive.get_file tool when not connected."""
    tool = DriveGetFileTool()
    r = tool.run(file_id="test_id")
    assert r.success is False
    assert "not connected" in r.error.lower() or "connect" in r.error.lower()
    print("✓ Test 7 PASSED: Get file tool when not connected")


def test_drive_read_tool_not_connected():
    """Test drive.read tool when not connected."""
    tool = DriveReadFileTool()
    r = tool.run(file_id="test_id")
    assert r.success is False
    assert "not connected" in r.error.lower() or "connect" in r.error.lower()
    print("✓ Test 8 PASSED: Read tool when not connected")


def test_drive_list_folder_tool_not_connected():
    """Test drive.list_folder tool when not connected."""
    tool = DriveListFolderTool()
    r = tool.run(folder_id="test_folder")
    assert r.success is False
    assert "not connected" in r.error.lower() or "connect" in r.error.lower()
    print("✓ Test 9 PASSED: List folder tool when not connected")


def test_drive_tools_permissions():
    """Test that tools have correct permissions."""
    tools = get_drive_tools()
    for tool in tools:
        assert hasattr(tool, "permissions")
        assert isinstance(tool.permissions, list)
        assert len(tool.permissions) > 0
    print("✓ Test 10 PASSED: Tools have permissions")


def test_drive_service_initialization():
    """Test GoogleDriveService initialization."""
    auth = GoogleDriveAuth()
    service = GoogleDriveService(auth)
    assert service.auth is auth
    assert service.service is None  # Not connected yet
    print("✓ Test 10 PASSED: Drive service initialization")


def test_search_files_no_service():
    """Test search_files when service not available."""
    auth = GoogleDriveAuth()
    service = GoogleDriveService(auth)
    results = service.search_files("test query")
    assert results == []
    print("✓ Test 11 PASSED: Search without service returns empty")


def test_get_file_metadata_no_service():
    """Test get_file_metadata without service."""
    auth = GoogleDriveAuth()
    service = GoogleDriveService(auth)
    meta = service.get_file_metadata("test_id")
    assert meta is None
    print("✓ Test 12 PASSED: Get file metadata without service")


def test_get_file_content_no_service():
    """Test get_file_content without service."""
    auth = GoogleDriveAuth()
    service = GoogleDriveService(auth)
    success, content, error = service.get_file_content("test_id")
    assert success is False
    assert content is None
    assert "Not connected" in error
    print("✓ Test 13 PASSED: Get file content without service")


def test_list_folder_no_service():
    """Test list_files_in_folder without service."""
    auth = GoogleDriveAuth()
    service = GoogleDriveService(auth)
    files = service.list_files_in_folder("folder_id")
    assert files == []
    print("✓ Test 14 PASSED: List folder without service")


def test_ensure_service_not_connected():
    """Test _ensure_service returns False when not connected."""
    auth = GoogleDriveAuth()
    service = GoogleDriveService(auth)
    result = service._ensure_service()
    assert result is False
    print("✓ Test 15 PASSED: _ensure_service returns False when not connected")


def test_google_drive_tools_registered_in_registry():
    """Test that all Google Drive tools are in the enhanced registry."""
    reg = __import__("jarvis.tools").tools.get_enhanced_registry()
    names = [t["name"] for t in reg.list_tools()]

    expected = [
        "drive.connect",
        "drive.disconnect",
        "drive.status",
        "drive.search",
        "drive.get_file",
        "drive.read",
        "drive.list_folder",
    ]
    for name in expected:
        assert name in names, f"Missing tool: {name}"
    print("✓ Test 16 PASSED: All Drive tools in enhanced registry")


def test_drive_auth_token_path():
    """Test that token path is correctly constructed."""
    auth = GoogleDriveAuth()
    assert auth.token_path.endswith("google_drive_token.json")
    print("✓ Test 17 PASSED: Token path construction")


def test_drive_auth_client_secrets_path():
    """Test that client secrets path is correctly constructed."""
    auth = GoogleDriveAuth()
    assert auth.client_secrets_path.endswith("google_client_secrets.json")
    print("✓ Test 18 PASSED: Client secrets path construction")


def test_drive_scopes():
    """Test that Drive scopes are correct."""
    from jarvis.google_drive import DRIVE_SCOPES
    assert "https://www.googleapis.com/auth/drive.readonly" in DRIVE_SCOPES
    assert len(DRIVE_SCOPES) == 1
    print("✓ Test 19 PASSED: Drive scopes correct")


def test_supported_mime_types():
    """Test supported MIME types are defined."""
    from jarvis.google_drive import SUPPORTED_MIME_TYPES
    assert "application/vnd.google-apps.document" in SUPPORTED_MIME_TYPES
    assert "application/pdf" in SUPPORTED_MIME_TYPES
    assert "text/plain" in SUPPORTED_MIME_TYPES
    print("✓ Test 20 PASSED: Supported MIME types defined")


def run_all():
    test_drive_tools_registered()
    test_drive_auth_initialization()
    test_drive_connected_false_initially()
    test_drive_status_structure()
    test_drive_auth_credentials_none_initially()
    test_drive_status_fields()
    test_drive_auth_credentials_none_initially()
    test_drive_status_fields()
    test_drive_connect_tool_not_connected()
    test_drive_disconnect_tool()
    test_drive_status_tool()
    test_drive_search_tool_not_connected()
    test_drive_get_file_tool_not_connected()
    test_drive_read_tool_not_connected()
    test_drive_list_folder_tool_not_connected()
    test_drive_tools_permissions()
    test_drive_service_initialization()
    test_search_files_no_service()
    test_get_file_metadata_no_service()
    test_get_file_content_no_service()
    test_list_folder_no_service()
    test_ensure_service_not_connected()
    test_google_drive_tools_registered_in_registry()
    test_drive_auth_token_path()
    test_drive_auth_client_secrets_path()
    test_drive_scopes()
    test_supported_mime_types()
    print("\n=== ALL PHASE 7 GOOGLE DRIVE TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
