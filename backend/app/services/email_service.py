"""
Microsoft Graph API email service.
Reads, searches, sends, and replies to emails using the stored OAuth tokens.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.oauth_account import OAuthAccount

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = (
    f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}"
    "/oauth2/v2.0/token"
)
# Buffer: refresh token 5 minutes before it actually expires
_EXPIRY_BUFFER = timedelta(minutes=5)


class EmailServiceError(Exception):
    pass


class EmailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _get_oauth_account(self, user_id: int) -> OAuthAccount:
        result = await self.db.execute(
            select(OAuthAccount).where(
                OAuthAccount.user_id == user_id,
                OAuthAccount.provider == "microsoft",
            )
        )
        account = result.scalar_one_or_none()
        if not account or not account.access_token:
            raise EmailServiceError(
                "No Microsoft account linked. Please log out and log in again "
                "to grant email permissions."
            )
        return account

    async def _get_valid_token(self, user_id: int) -> str:
        """Return a valid access token, refreshing if it is close to expiry."""
        account = await self._get_oauth_account(user_id)

        now = datetime.now(timezone.utc)
        expired = (
            account.token_expires_at is None
            or account.token_expires_at - _EXPIRY_BUFFER <= now
        )

        if expired:
            if not account.refresh_token:
                raise EmailServiceError(
                    "Session expired and no refresh token available. "
                    "Please log out and log in again."
                )
            new_tokens = await self._refresh_token(account.refresh_token)
            account.access_token = new_tokens["access_token"]
            if new_tokens.get("refresh_token"):
                account.refresh_token = new_tokens["refresh_token"]
            account.token_expires_at = now + timedelta(
                seconds=new_tokens.get("expires_in", 3600)
            )
            await self.db.commit()

        return account.access_token

    async def _refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "client_id": settings.MICROSOFT_CLIENT_ID,
                    "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": (
                        "offline_access Mail.Read Mail.Send User.Read"
                    ),
                },
            )
            resp.raise_for_status()
            return resp.json()

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Email operations
    # ------------------------------------------------------------------

    async def list_messages(
        self,
        user_id: int,
        folder: str = "inbox",
        top: int = 10,
        filter_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List emails from a mail folder."""
        token = await self._get_valid_token(user_id)

        folder_map = {
            "inbox": "inbox",
            "sent": "sentitems",
            "drafts": "drafts",
            "deleted": "deleteditems",
            "junk": "junkemail",
        }
        folder_id = folder_map.get(folder.lower(), folder)

        params: Dict[str, Any] = {
            "$top": min(top, 25),
            "$orderby": "receivedDateTime desc",
            "$select": (
                "id,subject,from,toRecipients,receivedDateTime,"
                "isRead,bodyPreview,hasAttachments"
            ),
        }
        if filter_query:
            params["$filter"] = filter_query

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/mailFolders/{folder_id}/messages",
                headers=self._auth_headers(token),
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

        return [self._format_message_summary(m) for m in data.get("value", [])]

    async def get_message(
        self, user_id: int, message_id: str
    ) -> Dict[str, Any]:
        """Fetch a single message with full body."""
        token = await self._get_valid_token(user_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/messages/{message_id}",
                headers=self._auth_headers(token),
                params={
                    "$select": (
                        "id,subject,from,toRecipients,ccRecipients,"
                        "receivedDateTime,isRead,body,hasAttachments"
                    )
                },
                timeout=20,
            )
            resp.raise_for_status()
            msg = resp.json()

        return self._format_message_full(msg)

    async def search_messages(
        self, user_id: int, query: str, top: int = 10
    ) -> List[Dict[str, Any]]:
        """Full-text search across all mail."""
        token = await self._get_valid_token(user_id)
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/messages",
                headers=self._auth_headers(token),
                params={
                    "$search": f'"{query}"',
                    "$top": min(top, 25),
                    "$select": (
                        "id,subject,from,toRecipients,receivedDateTime,"
                        "isRead,bodyPreview"
                    ),
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

        return [self._format_message_summary(m) for m in data.get("value", [])]

    async def send_message(
        self,
        user_id: int,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        body_type: str = "HTML",
    ) -> Dict[str, Any]:
        """Send a new email."""
        token = await self._get_valid_token(user_id)

        to_recipients = [{"emailAddress": {"address": a}} for a in to]
        cc_recipients = [{"emailAddress": {"address": a}} for a in (cc or [])]

        payload: Dict[str, Any] = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": to_recipients,
            },
            "saveToSentItems": True,
        }
        if cc_recipients:
            payload["message"]["ccRecipients"] = cc_recipients

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/sendMail",
                headers={**self._auth_headers(token), "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()

        return {"status": "sent", "to": to, "subject": subject}

    async def reply_to_message(
        self,
        user_id: int,
        message_id: str,
        body: str,
        reply_all: bool = False,
        body_type: str = "HTML",
    ) -> Dict[str, Any]:
        """Reply to an existing message."""
        token = await self._get_valid_token(user_id)

        endpoint = "replyAll" if reply_all else "reply"
        payload = {
            "message": {},
            "comment": body,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/messages/{message_id}/{endpoint}",
                headers={**self._auth_headers(token), "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()

        return {"status": "replied", "message_id": message_id}

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _format_message_summary(self, msg: Dict) -> Dict[str, Any]:
        sender = msg.get("from", {}).get("emailAddress", {})
        return {
            "id": msg.get("id", ""),
            "subject": msg.get("subject", "(no subject)"),
            "from": sender.get("address", ""),
            "from_name": sender.get("name", ""),
            "to": [
                r.get("emailAddress", {}).get("address", "")
                for r in msg.get("toRecipients", [])
            ],
            "received": msg.get("receivedDateTime", ""),
            "is_read": msg.get("isRead", True),
            "preview": msg.get("bodyPreview", ""),
            "has_attachments": msg.get("hasAttachments", False),
        }

    def _format_message_full(self, msg: Dict) -> Dict[str, Any]:
        summary = self._format_message_summary(msg)
        body = msg.get("body", {})
        summary["body"] = body.get("content", "")
        summary["body_type"] = body.get("contentType", "text")
        summary["cc"] = [
            r.get("emailAddress", {}).get("address", "")
            for r in msg.get("ccRecipients", [])
        ]
        return summary
