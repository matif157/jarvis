"""Phase 9 Email/Messaging Tests"""


from jarvis.email import (
    EmailAccountConfig,
    EmailAccountManager,
    EmailClient,
    EmailConnectTool,
    EmailDisconnectTool,
    EmailListFoldersTool,
    EmailReadTool,
    EmailSearchTool,
    EmailSendTool,
    EmailStatusTool,
    get_email_tools,
)


def test_email_tools_registered():
    """Test that all Email tools are registered."""
    reg = __import__('jarvis.tools').tools.get_enhanced_registry()
    names = [t['name'] for t in reg.list_tools()]

    expected = [
        "email.connect",
        "email.disconnect",
        "email.status",
        "email.search",
        "email.read",
        "email.send",
        "email.list_folders",
    ]
    for name in expected:
        assert name in names, f"Missing tool: {name}"
    print("✓ Test 1 PASSED: All Email tools registered")


def test_email_account_manager():
    """Test EmailAccountManager initialization."""
    manager = EmailAccountManager()
    assert manager.auth is not None
    print("✓ Test 1 PASSED: EmailAccountManager initialization")


def test_email_account_config():
    """Test EmailAccountConfig creation."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
        auth_token="test_token",
    )
    assert config.email == "test@example.com"
    assert config.provider == "gmail"
    assert config.imap_host == "imap.gmail.com"
    print("✓ Test 2 PASSED: EmailAccountConfig")


def test_email_account_manager_init():
    """Test EmailAccountManager initialization."""
    manager = EmailAccountManager()
    assert manager.auth is not None
    assert manager._clients == {}
    print("✓ Test 2 PASSED: EmailAccountManager init")


def test_get_accounts_empty():
    """Test getting accounts when none configured."""
    manager = EmailAccountManager()
    accounts = manager.get_accounts()
    assert isinstance(accounts, list)
    print("✓ Test 3 PASSED: Get accounts empty")


def test_connect_tool_not_configured():
    """Test connect tool without credentials."""
    tool = EmailConnectTool()
    r = tool.run(email="test@example.com", password="wrong", provider="gmail")
    # Should fail without valid credentials
    print("✓ Test 4 PASSED: Connect tool exists")


def test_disconnect_tool():
    """Test disconnect tool."""
    tool = EmailDisconnectTool()
    r = tool.run(email="test@example.com")
    # Should succeed (returns True even if account didn't exist)
    assert r.success is True
    print("✓ Test 5 PASSED: Disconnect tool")


def test_status_tool():
    """Test status tool."""
    tool = EmailStatusTool()
    r = tool.run()
    assert r.success
    assert "accounts" in r.result
    print("✓ Test 3 PASSED: Status tool")


def test_search_tool_not_connected():
    """Test search tool when not connected."""
    tool = EmailSearchTool()
    r = tool.run(email="test@example.com", query="test")
    assert not r.success
    assert "not connected" in r.error.lower()
    print("✓ Test 4 PASSED: Search tool rejects unconnected account")


def test_read_tool_not_connected():
    """Test read tool when not connected."""
    tool = EmailReadTool()
    r = tool.run(email="test@example.com", uid="123")
    assert not r.success
    assert "not connected" in r.error.lower()
    print("✓ Test 6 PASSED: Read tool rejects unconnected account")


def test_send_tool_not_connected():
    """Test send tool when not connected."""
    tool = EmailSendTool()
    r = tool.run(email="test@example.com", to=["test@example.com"], subject="Test", body_text="Test")
    assert not r.success
    assert "not connected" in r.error.lower()
    print("✓ Test 7 PASSED: Send tool rejects unconnected account")


def test_list_folders_not_connected():
    """Test list_folders when not connected."""
    tool = EmailListFoldersTool()
    r = tool.run(email="test@example.com")
    assert not r.success
    assert "not connected" in r.error.lower()
    print("✓ Test 8 PASSED: List folders rejects unconnected account")


def test_email_client_init():
    """Test EmailClient initialization."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
        auth_token="test_token",
    )
    client = EmailClient(config)
    assert client.config == config
    assert client.imap is None
    assert client.smtp is None
    print("✓ Test 9 PASSED: EmailClient initialization")


def test_email_client_ensure_imap():
    """Test _ensure_imap without connection."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
        auth_token="test_token",
    )
    client = EmailClient(config)
    result = client._ensure_imap()
    # Should fail without real credentials
    assert result is False
    print("✓ Test 10 PASSED: _ensure_imap without connection")


def test_email_client_ensure_smtp():
    """Test _ensure_smtp without connection."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
        auth_token="test_token",
    )
    client = EmailClient(config)
    result = client._ensure_smtp()
    assert result is False
    print("✓ Test 11 PASSED: _ensure_smtp without connection")


def test_email_client_close():
    """Test EmailClient close."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
        auth_token="test_token",
    )
    client = EmailClient(config)
    client.close()  # Should not raise
    print("✓ Test 12 PASSED: EmailClient close")


def test_email_config_dataclass():
    """Test EmailAccountConfig dataclass."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
    )
    assert config.email == "test@example.com"
    assert config.provider == "gmail"
    assert config.imap_host == "imap.gmail.com"
    assert config.smtp_port == 587
    assert config.enabled is True
    print("✓ Test 13 PASSED: EmailAccountConfig dataclass")


def test_imap_providers():
    """Test IMAP_PROVIDERS constant."""
    from jarvis.email import IMAP_PROVIDERS
    assert "gmail" in IMAP_PROVIDERS
    assert IMAP_PROVIDERS["gmail"] == "imap.gmail.com"
    assert "outlook" in IMAP_PROVIDERS
    print("✓ Test 14 PASSED: IMAP_PROVIDERS")


def test_smtp_providers():
    """Test SMTP_PROVIDERS constant."""
    from jarvis.email import SMTP_PROVIDERS
    assert "gmail" in SMTP_PROVIDERS
    assert SMTP_PROVIDERS["gmail"] == ("smtp.gmail.com", 587)
    print("✓ Test 15 PASSED: SMTP_PROVIDERS")


def test_email_account_manager_get_client():
    """Test getting client for unconfigured account."""
    manager = EmailAccountManager()
    client = manager._get_client("nonexistent@example.com")
    assert client is None
    print("✓ Test 16 PASSED: _get_client for unconfigured account")


def test_email_connect_tool_exists():
    """Test EmailConnectTool exists."""
    tool = EmailConnectTool()
    assert tool.name == "email.connect"
    assert "connect" in tool.description.lower()
    print("✓ Test 17 PASSED: EmailConnectTool exists")


def test_email_disconnect_tool_exists():
    """Test EmailDisconnectTool exists."""
    tool = EmailDisconnectTool()
    assert tool.name == "email.disconnect"
    print("✓ Test 18 PASSED: EmailDisconnectTool exists")


def test_email_status_tool_exists():
    """Test EmailStatusTool exists."""
    tool = EmailStatusTool()
    assert tool.name == "email.status"
    print("✓ Test 19 PASSED: EmailStatusTool exists")


def test_email_search_tool_exists():
    """Test EmailSearchTool exists."""
    tool = EmailSearchTool()
    assert tool.name == "email.search"
    print("✓ Test 19 PASSED: EmailSearchTool exists")


def test_email_read_tool_exists():
    """Test EmailReadTool exists."""
    tool = EmailReadTool()
    assert tool.name == "email.read"
    print("✓ Test 20 PASSED: EmailReadTool exists")


def test_email_send_tool_exists():
    """Test EmailSendTool exists."""
    tool = EmailSendTool()
    assert tool.name == "email.send"
    print("✓ Test 20 PASSED: EmailSendTool exists")


def test_email_list_folders_tool_exists():
    """Test EmailListFoldersTool exists."""
    tool = EmailListFoldersTool()
    assert tool.name == "email.list_folders"
    print("✓ Test 21 PASSED: EmailListFoldersTool exists")


def test_get_email_tools():
    """Test get_email_tools function."""
    tools = get_email_tools()
    assert len(tools) == 7
    names = [t.name for t in tools]
    expected = [
        "email.connect",
        "email.disconnect",
        "email.status",
        "email.search",
        "email.read",
        "email.send",
        "email.list_folders",
    ]
    for name in expected:
        assert name in names
    print("✓ Test 22 PASSED: get_email_tools returns 7 tools")


def test_email_account_manager_get_accounts():
    """Test get_accounts returns list."""
    manager = EmailAccountManager()
    accounts = manager.get_accounts()
    assert isinstance(accounts, list)
    print("✓ Test 23 PASSED: get_accounts returns list")


def test_email_account_config_defaults():
    """Test EmailAccountConfig defaults."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
    )
    assert config.enabled is True
    assert config.auth_token == ""
    print("✓ Test 24 PASSED: EmailAccountConfig defaults")


def test_email_client_close_no_error():
    """Test EmailClient.close doesn't raise."""
    config = EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
    )
    client = EmailClient(config)
    client.close()  # Should not raise
    print("✓ Test 25 PASSED: EmailClient.close no error")


def test_email_account_manager_auth():
    """Test EmailAccountManager has auth."""
    manager = EmailAccountManager()
    assert hasattr(manager, 'auth')
    assert manager.auth is not None
    print("✓ Test 26 PASSED: EmailAccountManager has auth")


def test_email_client_decode_header():
    """Test header decoding."""
    client = EmailClient(EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
    ))
    # Test header decoding
    decoded = client._decode_header("=?utf-8?b?SGVsbG8gV29ybGQ=?=")
    assert "Hello World" in decoded
    print("✓ Test 27 PASSED: Header decoding")


def test_email_client_parse_address():
    """Test address parsing."""
    client = EmailClient(EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
    ))
    parsed = client._parse_address("John Doe <john@example.com>")
    assert "John Doe" in parsed
    assert "john@example.com" in parsed
    print("✓ Test 28 PASSED: Address parsing")


def test_email_client_parse_address_list():
    """Test address list parsing."""
    client = EmailClient(EmailAccountConfig(
        email="test@example.com",
        provider="gmail",
        imap_host="imap.gmail.com",
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        username="test@example.com",
    ))
    parsed = client._parse_address_list("John <john@a.com>, Jane <jane@b.com>")
    assert len(parsed) == 2
    print("✓ Test 29 PASSED: Address list parsing")


def test_get_email_tools_function():
    """Test get_email_tools function."""
    from jarvis.email import get_email_tools
    tools = get_email_tools()
    assert len(tools) == 7
    print("✓ Test 30 PASSED: get_email_tools function")


def run_all():
    test_email_tools_registered()
    test_email_account_manager()
    test_email_account_config()
    test_email_account_manager_init()
    test_get_accounts_empty()
    test_connect_tool_not_configured()
    test_disconnect_tool()
    test_status_tool()
    test_search_tool_not_connected()
    test_read_tool_not_connected()
    test_send_tool_not_connected()
    test_list_folders_not_connected()
    test_email_client_init()
    test_email_client_ensure_imap()
    test_email_client_ensure_smtp()
    test_email_client_close()
    test_email_config_dataclass()
    test_imap_providers()
    test_smtp_providers()
    test_email_account_manager_get_client()
    test_email_connect_tool_exists()
    test_email_disconnect_tool_exists()
    test_email_status_tool_exists()
    test_email_search_tool_exists()
    test_email_read_tool_exists()
    test_email_send_tool_exists()
    test_email_list_folders_tool_exists()
    test_get_email_tools()
    test_email_account_manager_get_accounts()
    test_email_account_config_defaults()
    test_email_client_close_no_error()
    test_email_account_manager_auth()
    test_email_client_decode_header()
    test_email_client_parse_address()
    test_email_client_parse_address_list()
    test_get_email_tools_function()
    test_email_account_manager_auth()
    test_email_client_close_no_error()
    test_email_account_manager_auth()
    test_email_client_decode_header()
    test_email_client_parse_address()
    test_email_client_parse_address_list()
    test_get_email_tools_function()
    test_email_account_manager_auth()
    print("\n=== ALL PHASE 9 EMAIL TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
