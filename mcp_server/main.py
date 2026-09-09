"""
ALAI MCP Server — exposes the RAG knowledge base as a Claude.ai tool.

Transport: SSE (required for Claude.ai remote MCP integrations)
  GET  /sse       — Claude.ai connects here
  POST /messages/ — session message exchange

OAuth 2.0 (required by Claude.ai for remote MCP):
  GET  /.well-known/oauth-authorization-server — discovery
  POST /register                               — dynamic client registration
  GET  /authorize   — auto-approves, redirects to client
  POST /token                                  — exchange code / refresh token
  POST /revoke                                 — token revocation

Public URL: https://mcp-alai.antaragpt.com/sse

Environment variables:
  RAG_URL     — REST endpoint (default: http://backend:8000/api/rag/query)
  RAG_API_KEY — shared secret, must match the backend's RAG_API_KEY
  MCP_ISSUER  — OAuth issuer URL (default: https://mcp-alai.antaragpt.com)
  PORT        — listen port (default: 8001)
"""

import asyncio
import os
import secrets
import time

import httpx
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

RAG_URL = os.getenv("RAG_URL", "http://backend:8000/api/rag/query")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")
MCP_ISSUER = os.getenv("MCP_ISSUER", "https://mcp-alai.antaragpt.com")
PORT = int(os.getenv("PORT", "8001"))

ACCESS_TOKEN_TTL = 3600          # 1 hour
REFRESH_TOKEN_TTL = 30 * 86400  # 30 days
AUTH_CODE_TTL = 600              # 10 minutes


class InMemoryOAuthProvider(
    OAuthAuthorizationServerProvider[
        AuthorizationCode, RefreshToken, AccessToken
    ]
):
    """Auto-approving in-memory OAuth 2.0 provider for Claude.ai."""

    def __init__(self) -> None:
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._access_tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}

    async def get_client(
        self, client_id: str
    ) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        self._clients[client_info.client_id] = client_info

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=(
                params.redirect_uri_provided_explicitly
            ),
            resource=params.resource,
        )
        return construct_redirect_uri(
            str(params.redirect_uri), code=code, state=params.state
        )

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if code and code.client_id == client.client_id:
            return code
        return None

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        del self._auth_codes[authorization_code.code]

        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)

        self._access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + ACCESS_TOKEN_TTL,
            resource=authorization_code.resource,
        )
        self._refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + REFRESH_TOKEN_TTL,
            resource=authorization_code.resource,
        )
        return OAuthToken(
            access_token=access_token,
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        token = self._refresh_tokens.get(refresh_token)
        if token and token.client_id == client.client_id:
            if token.expires_at is None or token.expires_at > time.time():
                return token
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        del self._refresh_tokens[refresh_token.token]

        effective_scopes = scopes if scopes else refresh_token.scopes
        access_token = secrets.token_urlsafe(32)
        new_refresh_token = secrets.token_urlsafe(32)

        self._access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(time.time()) + ACCESS_TOKEN_TTL,
            resource=refresh_token.resource,
        )
        self._refresh_tokens[new_refresh_token] = RefreshToken(
            token=new_refresh_token,
            client_id=client.client_id,
            scopes=effective_scopes,
            expires_at=int(time.time()) + REFRESH_TOKEN_TTL,
            resource=refresh_token.resource,
        )
        return OAuthToken(
            access_token=access_token,
            expires_in=ACCESS_TOKEN_TTL,
            scope=" ".join(effective_scopes),
            refresh_token=new_refresh_token,
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        at = self._access_tokens.get(token)
        if at is None:
            return None
        if at.expires_at is not None and at.expires_at < time.time():
            del self._access_tokens[token]
            return None
        return at

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self._access_tokens.pop(token.token, None)
        self._refresh_tokens.pop(token.token, None)


mcp = MCPServer(
    "alai-rag",
    auth_server_provider=InMemoryOAuthProvider(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(MCP_ISSUER),
        resource_server_url=None,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp"],
            default_scopes=["mcp"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    ),
)


@mcp.custom_route("/", methods=["GET"])
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "alai-mcp"})


@mcp.tool()
async def search_documents(
    query: str,
    top_k: int = 5,
    source_filter: str | None = None,
) -> str:
    """Search the company knowledge base for relevant information.

    Returns ranked document chunks with source, section heading, and page
    references. Use this whenever the user asks about company policies,
    regulations, procedures, or any topic covered in internal documents.

    Args:
        query: Natural-language search query.
        top_k: Number of results to return (1-20, default 5).
        source_filter: Optional filename substring to restrict results.
    """
    payload: dict = {"query": query, "top_k": min(top_k, 20)}
    if source_filter:
        payload["source_filter"] = source_filter

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                RAG_URL,
                headers={
                    "Authorization": f"Bearer {RAG_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return f"RAG error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"RAG error: {e}"

    results = data.get("results", [])
    if not results:
        return "No relevant documents found."

    parts: list[str] = []
    for r in results:
        header = f"[{r['rank']}] {r['document']}"
        if r.get("heading"):
            header += f" — {r['heading']}"
        if r.get("pages"):
            header += f" (p. {r['pages']})"
        header += f"  [relevance: {r.get('relevance_score', 0):.0%}]"
        parts.append(f"{header}\n{r['content']}")

    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    asyncio.run(
        mcp.run_sse_async(
            host="0.0.0.0",
            port=PORT,
            sse_path="/sse",
            message_path="/messages/",
        )
    )
