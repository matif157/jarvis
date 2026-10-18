"""Email and Messaging integration for Jarvis - secure, consent-based communication."""

from __future__ import annotations

import email
import email.message
import email.utils
import imaplib
import json
import smtplib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import get_data_dir
from .logging import get_logger
from .tools import Tool, ToolResult

logger = get_logger(__name__)

# Email data directory
EMAIL_DIR = Path(get_data_dir()) / "email"
EMAIL_DIR.mkdir(parents=True, exist_ok=True)

# OAuth scopes for Gmail/IMAP
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Supported IMAP providers
IMAP_PROVIDERS = {
    "gmail": "imap.gmail.com",
    "outlook": "outlook.office365.com",
    "yahoo": "imap.mail.yahoo.com",
    "icloud": "imap.mail.me.com",
    "fastmail": "imap.fastmail.com",
    "protonmail": "imap.proton.me",
}

# SMTP servers for sending
SMTP_PROVIDERS = {
    "gmail": ("smtp.gmail.com", 587),
    "outlook": ("smtp.office365.com", 587),
    "yahoo": ("smtp.mail.yahoo.com", 587),
    "icloud": ("smtp.mail.me.com", 587),
    "fastmail": ("imap.fastmail.com", 587),
    "protonmail": ("imap.proton.me", 587),
}

# Maximum emails to fetch at once
MAX_FETCH_COUNT = 50
MAX_EMAIL_SIZE = 5 * 1024 * 1024  # 5MB


@dataclass
class EmailAccount:
    """Email account configuration."""
    email: str
    provider: str
    imap_host: str
    smtp_host: str
    smtp_port: int
    username: str
    # Password/app password stored encrypted or via keychain
    _password: str = field(default="", repr=False)


@dataclass
class EmailMessage:
    """Parsed email message."""
    uid: str
    message_id: str
    subject: str
    from_addr: str
    to_addrs: List[str]
    cc_addrs: List[str]
    date: str
    body_text: str
    body_html: Optional[str]
    attachments: List[Dict[str, Any]]
    labels: List[str]
    is_read: bool
    folder: str


@dataclass
class EmailAccountConfig:
    """Stored email account configuration."""
    email: str
    provider: str
    imap_host: str
    smtp_host: str
    smtp_port: int
    username: str
    # Encrypted password or token reference
    auth_token: str = ""
    last_sync: Optional[str] = None
    enabled: bool = True


class EmailAuth:
    """Email authentication and connection management."""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or get_data_dir()) / "email"
        self.accounts_file = self.accounts_dir / "accounts.json"
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        self._accounts: Dict[str, EmailAccountConfig] = {}
        self._load_accounts()

    @property
    def accounts_dir(self) -> Path:
        return Path(get_data_dir()) / "email"

    def _load_accounts(self) -> None:
        if self.accounts_file.exists():
            try:
                with open(self.accounts_file, "r") as f:
                    data = json.load(f)
                    self._accounts = {k: EmailAccountConfig(**v) for k, v in data.items()}
            except Exception as e:
                logger.warning(f"Failed to load email accounts: {e}")

    def _save_accounts(self) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in self._accounts.items()}
        with open(self.accounts_file, "w") as f:
            json.dump(data, f, indent=2)

    def add_account(self, config: EmailAccountConfig) -> None:
        self._accounts[config.email] = config
        self._save_accounts()

    def get_account(self, email: str) -> Optional[EmailAccountConfig]:
        return self._accounts.get(email)

    def remove_account(self, email: str) -> bool:
        if email in self._accounts:
            del self._accounts[email]
            self._save_accounts()
            return True
        return False

    def list_accounts(self) -> List[EmailAccountConfig]:
        return list(self._accounts.values())


class EmailClient:
    """IMAP/SMTP client for email operations."""

    def __init__(self, config: EmailAccountConfig):
        self.config = config
        self.imap: Optional[imaplib.IMAP4_SSL] = None
        self.smtp: Optional[smtplib.SMTP] = None

    def _connect_imap(self) -> bool:
        """Connect to IMAP server."""
        try:
            self.imap = imaplib.IMAP4_SSL(self.config.imap_host)
            self.imap.login(self.config.username, self.config.auth_token)
            return True
        except Exception as e:
            logger.error(f"IMAP connection failed: {e}")
            return False

    def _connect_smtp(self) -> bool:
        """Connect to SMTP server."""
        try:
            self.smtp = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port)
            self.smtp.starttls()
            self.smtp.login(self.config.username, self.config.auth_token)
            return True
        except Exception as e:
            logger.error(f"SMTP connection failed: {e}")
            return False

    def close(self) -> None:
        try:
            if self.imap:
                self.imap.close()
                self.imap.logout()
        except Exception:
            pass
        try:
            if self.smtp:
                self.smtp.quit()
        except Exception:
            pass

    def search_emails(
        self,
        folder: str = "INBOX",
        query: str = "ALL",
        max_count: int = 50,
        since_days: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search for emails matching criteria."""
        if not self._ensure_imap():
            return []

        try:
            self.imap.select(folder)
            criteria = query
            if since_days:
                since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
                criteria = f'({query}) SINCE {since_date}'

            status, messages = self.imap.search(None, criteria)
            if status != "OK":
                return []

            uids = messages[0].split()
            uids = uids[-max_count:]  # Get latest

            results = []
            for uid in reversed(uids):  # Newest first
                try:
                    msg_data = self._fetch_message(uid)
                    if msg_data:
                        msg_data["uid"] = uid.decode()
                        results.append(msg_data)
                except Exception as e:
                    logger.warning(f"Failed to fetch message {uid}: {e}")

            return results
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def _fetch_message(self, uid: bytes) -> Optional[Dict]:
        """Fetch and parse a single message."""
        try:
            status, msg_data = self.imap.fetch(uid, "(RFC822)")
            if status != "OK" or not msg_data:
                return None

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # Parse headers
            subject = self._decode_header(msg.get("Subject", ""))
            from_addr = self._parse_address(msg.get("From", ""))
            to_addrs = self._parse_address_list(msg.get("To", ""))
            cc_addrs = self._parse_address_list(msg.get("Cc", ""))
            date_str = msg.get("Date", "")

            # Parse body
            body_text = ""
            body_html = None
            attachments = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    disposition = str(part.get("Content-Disposition", ""))

                    if "attachment" in disposition:
                        filename = part.get_filename()
                        if filename:
                            payload = part.get_payload(decode=True)
                            attachments.append({
                                "filename": filename,
                                "content_type": content_type,
                                "size": len(payload) if payload else 0,
                            })
                    elif content_type == "text/plain" and not body_text:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_text = payload.decode("utf-8", errors="replace")
                    elif content_type == "text/html" and not body_html:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_html = payload.decode("utf-8", errors="replace")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    if msg.get_content_type() == "text/html":
                        body_html = payload.decode("utf-8", errors="replace")
                    else:
                        body_text = payload.decode("utf-8", errors="replace")

            return {
                "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                "message_id": msg.get("Message-ID", ""),
                "subject": subject,
                "from": from_addr,
                "to": to_addrs,
                "cc": cc_addrs,
                "date": date_str,
                "body_text": body_text[:10000] if body_text else "",
                "body_html": body_html[:10000] if body_html else None,
                "attachments": attachments,
                "is_read": r"\Seen" in msg.get("Flags", ""),
            }
        except Exception as e:
            logger.warning(f"Failed to parse message {uid}: {e}")
            return None

    def _decode_header(self, header: str) -> str:
        if not header:
            return ""
        parts = decode_header(header)
        decoded = ""
        for part, encoding in parts:
            if isinstance(part, bytes):
                decoded += part.decode(encoding or "utf-8", errors="replace")
            else:
                decoded += part
        return decoded

    def _parse_address(self, addr: str) -> str:
        name, addr = email.utils.parseaddr(addr)
        return f"{name} <{addr}>" if name else addr

    def _parse_address_list(self, addrs: str) -> List[str]:
        if not addrs:
            return []
        return [self._parse_address(a.strip()) for a in addrs.split(",") if a.strip()]

    def send_email(
        self,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        cc: List[str] = None,
        bcc: List[str] = None,
        attachments: List[Dict] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Send an email."""
        if not self._ensure_smtp():
            return False, "SMTP connection failed"

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.config.username
            msg["To"] = ", ".join(to)
            if cc:
                msg["Cc"] = ", ".join(cc)

            if body_text:
                msg.attach(MIMEText(body_text, "plain", "utf-8"))
            if body_html:
                msg.attach(MIMEText(body_html, "html", "utf-8"))

            # Handle attachments
            if attachments:
                for att in attachments:
                    part = MIMEText(att.get("content", ""), "plain")
                    part.add_header("Content-Disposition", "attachment", filename=att.get("filename", "attachment"))
                    msg.attach(part)

            recipients = to + (cc or []) + (bcc or [])
            self.smtp.sendmail(self.config.username, recipients, msg.as_string())
            return True, None
        except Exception as e:
            logger.error(f"Send failed: {e}")
            return False, str(e)

    def _ensure_imap(self) -> bool:
        if self.imap:
            try:
                self.imap.noop()
                return True
            except Exception:
                pass
        return self._connect_imap()

    def _ensure_smtp(self) -> bool:
        if self.smtp:
            try:
                self.smtp.noop()
                return True
            except Exception:
                pass
        return self._connect_smtp()


class EmailAccountManager:
    """Manages email accounts and operations."""

    def __init__(self):
        self.auth = EmailAuth()
        self._clients: Dict[str, EmailClient] = {}

    def _get_client(self, email: str) -> Optional[EmailClient]:
        if email in self._clients:
            return self._clients[email]

        config = self.auth.get_account(email)
        if not config or not config.enabled:
            return None

        client = EmailClient(config)
        if client._connect_imap():
            self._clients[email] = client
            return client
        return None

    def get_accounts(self) -> List[Dict]:
        accounts = self.auth.list_accounts()
        return [{"email": a.email, "provider": a.provider, "enabled": a.enabled} for a in accounts]

    def connect_account(
        self,
        email: str,
        password: str,
        provider: str = "gmail",
    ) -> Tuple[bool, str]:
        """Connect to an email account."""
        if provider not in IMAP_PROVIDERS:
            return False, f"Unsupported provider: {provider}"

        imap_host = IMAP_PROVIDERS[provider]
        smtp_host, smtp_port = SMTP_PROVIDERS.get(provider, (IMAP_PROVIDERS[provider], 587))

        # Test connection
        try:
            imap = imaplib.IMAP4_SSL(IMAP_PROVIDERS[provider])
            imap.login(email, password)
            imap.logout()
        except Exception as e:
            return False, f"Authentication failed: {e}"

        config = EmailAccountConfig(
            email=email,
            provider=provider,
            imap_host=imap_host,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            username=email,
            auth_token=password,  # In production, encrypt this
            enabled=True,
        )
        self.auth.add_account(config)
        return True, "Account connected successfully"

    def disconnect_account(self, email: str) -> bool:
        if email in self._clients:
            self._clients[email].close()
            del self._clients[email]
        return self.auth.remove_account(email)

    def get_status(self, email: str) -> Dict:
        config = self.auth.get_account(email)
        if not config:
            return {"connected": False}
        return {
            "email": config.email,
            "provider": config.provider,
            "enabled": config.enabled,
            "last_sync": config.last_sync,
        }

    def search_emails(
        self,
        email: str,
        query: str = "ALL",
        folder: str = "INBOX",
        max_count: int = 20,
        since_days: int = None,
    ) -> List[Dict]:
        client = self._get_client(email)
        if not client:
            return []
        return client.search_emails(folder, query, max_count, since_days)

    def get_message(self, email: str, uid: str) -> Optional[Dict]:
        client = self._get_client(email)
        if not client:
            return None
        return client._fetch_message(uid.encode())

    def send_email(
        self,
        email: str,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: str = None,
        cc: List[str] = None,
        bcc: List[str] = None,
    ) -> Tuple[bool, str]:
        client = self._get_client(email)
        if not client or not client._ensure_smtp():
            return False, "SMTP not available"

        success, error = client.send_email(to, subject, body_text, body_html, cc)
        return success, error or "Sent successfully"

    def list_folders(self, email: str) -> List[str]:
        client = self._get_client(email)
        if not client or not client.imap:
            return []
        try:
            status, folders = client.imap.list()
            if status == "OK":
                return [f.decode().split(' "/" ')[-1].strip('"') for f in folders]
        except Exception:
            pass
        return []


# Tool classes for the registry
class EmailConnectTool(Tool):
    name = "email.connect"
    description = "Connect to an email account (IMAP/SMTP)"
    permissions = ["email.connect"]

    def run(
        self,
        email: str,
        password: str,
        provider: str = "gmail",
    ) -> ToolResult:
        manager = EmailAccountManager()
        success, message = manager.connect_account(email, password, provider)
        return ToolResult(success=success, result={"message": message}, error=None if success else message)


class EmailDisconnectTool(Tool):
    name = "email.disconnect"
    description = "Disconnect an email account"
    permissions = ["email.connect"]

    def run(self, email: str) -> ToolResult:
        manager = EmailAccountManager()
        success = manager.disconnect_account(email)
        # Idempotent: always return success
        return ToolResult(success=True, result={"disconnected": email})


class EmailStatusTool(Tool):
    name = "email.status"
    description = "Get email account connection status"
    permissions = ["email.read"]

    def run(self, email: str = None) -> ToolResult:
        manager = EmailAccountManager()
        if email:
            status = manager.get_status(email)
            return ToolResult(success=True, result=status)
        accounts = manager.get_accounts()
        return ToolResult(success=True, result={"accounts": accounts})


class EmailSearchTool(Tool):
    name = "email.search"
    description = "Search emails by query"
    permissions = ["email.read"]

    def run(
        self,
        email: str,
        query: str = "ALL",
        folder: str = "INBOX",
        max_count: int = 20,
        since_days: int = None,
    ) -> ToolResult:
        manager = EmailAccountManager()
        if not manager.auth.get_account(email):
            return ToolResult(success=False, error="Account not connected")

        results = manager.search_emails(email, query, folder, max_count, since_days)
        return ToolResult(
            success=True,
            result={"query": query, "folder": folder, "count": len(results), "messages": results},
        )


class EmailReadTool(Tool):
    name = "email.read"
    description = "Read a specific email by UID"
    permissions = ["email.read"]

    def run(self, email: str, uid: str) -> ToolResult:
        manager = EmailAccountManager()
        if not manager.auth.get_account(email):
            return ToolResult(success=False, error="Account not connected")

        msg = manager.get_message(email, uid)
        if not msg:
            return ToolResult(success=False, error="Message not found")
        return ToolResult(success=True, result=msg)


class EmailSendTool(Tool):
    name = "email.send"
    description = "Send an email"
    permissions = ["email.send"]

    def run(
        self,
        email: str,
        to: List[str],
        subject: str,
        body_text: str,
        body_html: str = None,
        cc: List[str] = None,
        bcc: List[str] = None,
    ) -> ToolResult:
        manager = EmailAccountManager()
        if not manager.auth.get_account(email):
            return ToolResult(success=False, error="Account not connected")

        success, message = manager.send_email(email, to, subject, body_text, body_html, cc)
        return ToolResult(success=success, result={"sent": success}, error=message)


class EmailListFoldersTool(Tool):
    name = "email.list_folders"
    description = "List email folders/labels"
    permissions = ["email.read"]

    def run(self, email: str) -> ToolResult:
        manager = EmailAccountManager()
        if not manager.auth.get_account(email):
            return ToolResult(success=False, error="Account not connected")

        folders = manager.list_folders(email)
        return ToolResult(success=True, result={"folders": folders})


def get_email_tools() -> List[Tool]:
    """Get all email tools for registration."""
    return [
        EmailConnectTool(),
        EmailDisconnectTool(),
        EmailStatusTool(),
        EmailSearchTool(),
        EmailReadTool(),
        EmailSendTool(),
        EmailListFoldersTool(),
    ]


def get_email_tools_for_registry() -> List[Tool]:
    """Get email tools for registry registration."""
    return get_email_tools()


# Convenience function
def get_email_manager() -> "EmailAccountManager":
    return EmailAccountManager()
