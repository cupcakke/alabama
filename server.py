"""Remote MCP server for searching and reading this repository's Markdown files.

The server exposes the read-only ``search`` and ``fetch`` tools expected by
research clients, plus a few repository-oriented helper tools.  HTTP clients
should connect to ``/mcp`` using Streamable HTTP.  A legacy SSE endpoint is
also mounted at ``/sse`` for clients that have not moved to Streamable HTTP.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

logger = logging.getLogger("alabama-mcp")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPOSITORY_ROOT = Path(
    os.getenv("MCP_ROOT", str(Path(__file__).resolve().parent))
).expanduser().resolve()
AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
CITATION_BASE_URL = os.getenv(
    "CITATION_BASE_URL",
    "https://github.com/cupcakke/alabama/blob/main",
).strip().rstrip("/")
MAX_SEARCH_RESULTS = max(1, min(int(os.getenv("MAX_SEARCH_RESULTS", "10")), 50))
MAX_FETCH_CHARS = max(1, int(os.getenv("MAX_FETCH_CHARS", "2000000")))
MAX_SNIPPET_CHARS = max(80, min(int(os.getenv("MAX_SNIPPET_CHARS", "900")), 5000))
ALLOW_QUERY_TOKEN = os.getenv("MCP_ALLOW_QUERY_TOKEN", "false").lower() in {
    "1",
    "true",
    "yes",
}

# Directory names that are implementation details, not repository documents.
# In particular, never accidentally expose Git metadata or a virtualenv.
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


# ---------------------------------------------------------------------------
# Document indexing and retrieval
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DocumentInfo:
    """Stable metadata for one Markdown file."""

    id: str
    path: Path
    size_bytes: int
    modified_at: str


class MarkdownRepository:
    """Small, dependency-free Markdown index for a repository on disk.

    The repository is intentionally scanned from disk instead of copied into a
    second data store.  That keeps the deployment simple and means a mounted
    volume or an updated checkout is reflected on the next request.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, tuple[int, int, str]] = {}
        self._lock = threading.RLock()

    def _is_allowed_path(self, path: Path) -> bool:
        if path.is_symlink() or path.suffix.lower() != ".md":
            return False
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return False
        return not any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts)

    def documents(self) -> list[DocumentInfo]:
        """Return every Markdown document below the repository root."""
        if not self.root.exists():
            raise RuntimeError(f"MCP_ROOT does not exist: {self.root}")

        found: list[DocumentInfo] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or not self._is_allowed_path(path):
                continue
            try:
                relative = path.relative_to(self.root).as_posix()
                stat = path.stat()
            except (OSError, ValueError) as exc:
                logger.warning("Skipping unreadable file %s: %s", path, exc)
                continue
            found.append(
                DocumentInfo(
                    id=relative,
                    path=path,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                )
            )

        found.sort(key=lambda item: item.id.casefold())
        return found

    def get(self, document_id: str) -> DocumentInfo:
        """Resolve a document ID without allowing path traversal."""
        if not document_id or "\\" in document_id:
            raise KeyError(document_id)

        # IDs are emitted by documents(), so matching against that index also
        # prevents symlinks and non-Markdown files from being fetched.
        for info in self.documents():
            if info.id == document_id:
                return info
        raise KeyError(document_id)

    def read(self, document_id: str) -> tuple[DocumentInfo, str]:
        info = self.get(document_id)
        try:
            stat = info.path.stat()
        except OSError as exc:
            raise KeyError(document_id) from exc

        cache_key = info.id
        signature = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None and cached[:2] == signature:
                return info, cached[2]

        try:
            text = info.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise KeyError(document_id) from exc

        with self._lock:
            self._cache[cache_key] = (signature[0], signature[1], text)
        return info, text


repository = MarkdownRepository(REPOSITORY_ROOT)


def _fold(value: str) -> str:
    """Case- and accent-insensitive representation for human search."""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[\w\u0080-\uffff]{2,}", _fold(query))]


def _score_document(query: str, info: DocumentInfo, text: str) -> float:
    """Rank a document using deterministic lexical relevance signals."""
    folded_query = _fold(query).strip()
    folded_text = _fold(text)
    folded_title = _fold(info.id)
    terms = _query_terms(query)
    if not folded_query or not terms:
        return 0.0

    score = 0.0
    if folded_query in folded_title:
        score += 30.0
    if folded_query in folded_text:
        score += 18.0

    for term in terms:
        title_hits = folded_title.count(term)
        body_hits = folded_text.count(term)
        if title_hits:
            score += min(title_hits, 3) * 8.0
        if body_hits:
            # A large document should not win merely because a common term is
            # repeated hundreds of times.
            score += min(body_hits, 20) * 1.5

    # Reward documents that contain all query terms, which is useful for names
    # and case numbers in legal records.
    if terms and all(term in folded_text or term in folded_title for term in terms):
        score += 12.0
    return score


def _snippet(text: str, query: str, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    """Return a compact context window around the first matching term."""
    if not text:
        return ""
    folded_text = _fold(text)
    terms = _query_terms(query)
    positions = [folded_text.find(term) for term in terms if folded_text.find(term) >= 0]
    start = min(positions) if positions else 0
    half_window = max_chars // 2
    left = max(0, start - half_window)
    right = min(len(text), left + max_chars)
    if right - left < max_chars:
        left = max(0, right - max_chars)
    value = text[left:right].strip()
    if left > 0:
        value = "…" + value
    if right < len(text):
        value += "…"
    return value


def _line_count(text: str) -> int:
    return text.count("\n") + (1 if text else 0)


def _title(document_id: str) -> str:
    return Path(document_id).name


def _citation_url(document_id: str) -> str:
    """Build a stable, human-readable citation URL.

    ``PUBLIC_BASE_URL`` points to the deployed server and is preferred when it
    is set.  The server exposes those citations under ``/documents``.  Without
    it, citations point directly at the configured GitHub blob base.  The
    document ID is encoded as one URL path segment so spaces and accented
    filenames remain unambiguous.
    """
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/documents/{quote(document_id, safe='')}"
    return f"{CITATION_BASE_URL}/{quote(document_id, safe='')}"


# ---------------------------------------------------------------------------
# MCP output models
# ---------------------------------------------------------------------------

class SearchResult(BaseModel):
    id: str = Field(description="Stable Markdown document ID passed to fetch")
    title: str = Field(description="Human-readable document filename")
    url: str = Field(description="Canonical URL for citing the document")


class SearchOutput(BaseModel):
    results: list[SearchResult] = Field(
        description="Relevant Markdown documents, ordered by relevance"
    )


class FetchOutput(BaseModel):
    id: str = Field(description="Stable Markdown document ID")
    title: str = Field(description="Human-readable document filename")
    text: str = Field(description="Full Markdown document text")
    url: str = Field(description="Canonical URL for citing the document")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Document metadata and truncation information"
    )


class RepositoryDocument(BaseModel):
    id: str
    title: str
    size_bytes: int
    modified_at: str
    url: str


class RepositoryDocumentsOutput(BaseModel):
    documents: list[RepositoryDocument]
    total: int


class SearchDocumentsResult(BaseModel):
    id: str
    title: str
    score: float
    snippet: str
    url: str


class SearchDocumentsOutput(BaseModel):
    query: str
    results: list[SearchDocumentsResult]


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

server_instructions = """
This read-only MCP server provides access to every Markdown file in the
Alabama repository. Use search(query) first to find relevant documents, then
use fetch(id) to retrieve the complete text of a selected result. Document IDs
are the repository-relative Markdown paths returned by search. The source
contains legal and personal records; do not infer facts that are not present
in the retrieved documents, and cite the returned URLs.
""".strip()

mcp = FastMCP(
    name="Alabama Markdown Repository",
    instructions=server_instructions,
    stateless_http=True,
    # Streamable HTTP can return either JSON or SSE.  Keeping SSE enabled also
    # works with older clients while the endpoint remains /mcp.
    json_response=False,
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8000")),
)


@mcp.tool()
def search(query: str) -> SearchOutput:
    """Search all Markdown files and return citable document IDs.

    Use a natural-language query containing the names, dates, case numbers, or
    topics you need.  This tool returns only lightweight result metadata; call
    fetch with a returned ID to read the document text.
    """
    query = query.strip()
    if not query:
        return SearchOutput(results=[])

    ranked: list[tuple[float, DocumentInfo]] = []
    for info in repository.documents():
        try:
            _, text = repository.read(info.id)
        except KeyError:
            continue
        score = _score_document(query, info, text)
        if score > 0:
            ranked.append((score, info))

    ranked.sort(key=lambda pair: (-pair[0], pair[1].id.casefold()))
    return SearchOutput(
        results=[
            SearchResult(
                id=info.id,
                title=_title(info.id),
                url=_citation_url(info.id),
            )
            for _, info in ranked[:MAX_SEARCH_RESULTS]
        ]
    )


@mcp.tool()
def fetch(id: str) -> FetchOutput:
    """Fetch the complete Markdown text for a document returned by search.

    The ``id`` must be copied exactly from a search result.  The response is
    read-only and includes metadata such as file size and line count.
    """
    try:
        info, text = repository.read(id)
    except KeyError as exc:
        raise ValueError(f"Markdown document not found: {id}") from exc

    truncated = len(text) > MAX_FETCH_CHARS
    returned_text = text[:MAX_FETCH_CHARS] if truncated else text
    metadata: dict[str, Any] = {
        "source": "alabama-markdown-repository",
        "path": info.id,
        "size_bytes": info.size_bytes,
        "line_count": _line_count(text),
        "last_modified": info.modified_at,
        "truncated": truncated,
    }
    if truncated:
        metadata["available_chars"] = len(text)
        metadata["returned_chars"] = len(returned_text)
        metadata[
            "note"
        ] = "The document exceeded MAX_FETCH_CHARS; use get_document for line-ranged retrieval."

    return FetchOutput(
        id=info.id,
        title=_title(info.id),
        text=returned_text,
        url=_citation_url(info.id),
        metadata=metadata,
    )


@mcp.tool()
def list_documents() -> RepositoryDocumentsOutput:
    """List every Markdown file available in the repository."""
    documents = repository.documents()
    return RepositoryDocumentsOutput(
        total=len(documents),
        documents=[
            RepositoryDocument(
                id=info.id,
                title=_title(info.id),
                size_bytes=info.size_bytes,
                modified_at=info.modified_at,
                url=_citation_url(info.id),
            )
            for info in documents
        ],
    )


@mcp.tool()
def search_documents(
    query: str,
    max_results: int = Field(
        default=10, ge=1, le=50, description="Maximum number of results"
    ),
) -> SearchDocumentsOutput:
    """Search with scores and text snippets for interactive MCP clients.

    The compatibility search tool is intentionally minimal.  Use this helper
    when you need snippets before deciding which document to fetch.
    """
    query = query.strip()
    max_results = max(1, min(int(max_results), 50))
    if not query:
        return SearchDocumentsOutput(query=query, results=[])

    ranked: list[tuple[float, DocumentInfo, str]] = []
    for info in repository.documents():
        try:
            _, text = repository.read(info.id)
        except KeyError:
            continue
        score = _score_document(query, info, text)
        if score > 0:
            ranked.append((score, info, text))

    ranked.sort(key=lambda item: (-item[0], item[1].id.casefold()))
    return SearchDocumentsOutput(
        query=query,
        results=[
            SearchDocumentsResult(
                id=info.id,
                title=_title(info.id),
                score=round(score, 3),
                snippet=_snippet(text, query),
                url=_citation_url(info.id),
            )
            for score, info, text in ranked[:max_results]
        ],
    )


@mcp.tool()
def get_document(
    id: str,
    start_line: int = Field(default=1, ge=1, description="First line, 1-based"),
    max_lines: int = Field(
        default=400, ge=1, le=5000, description="Maximum number of lines"
    ),
) -> str:
    """Read a line range from a Markdown document.

    This is a fallback for documents larger than a model's preferred context
    window.  For normal retrieval use fetch, which returns the whole document.
    """
    try:
        info, text = repository.read(id)
    except KeyError as exc:
        raise ValueError(f"Markdown document not found: {id}") from exc

    start_line = max(1, int(start_line))
    max_lines = max(1, min(int(max_lines), 5000))
    lines = text.splitlines()
    start_index = start_line - 1
    selected = lines[start_index : start_index + max_lines]
    end_line = start_index + len(selected)
    header = (
        f"# {info.id}\n"
        f"Lines {start_line}-{end_line} of {_line_count(text)}\n\n"
    )
    return header + "\n".join(selected)


# ---------------------------------------------------------------------------
# HTTP application, health check and authentication
# ---------------------------------------------------------------------------

async def health(_: Request) -> JSONResponse:
    try:
        count = len(repository.documents())
        status = "ok"
    except RuntimeError as exc:
        logger.error("Health check failed: %s", exc)
        count = 0
        status = "error"
    return JSONResponse(
        {
            "status": status,
            "service": "alabama-markdown-mcp",
            "documents": count,
            "auth": bool(AUTH_TOKEN),
        },
        status_code=200 if status == "ok" else 503,
    )


async def document_http(request: Request) -> PlainTextResponse | JSONResponse:
    """Human-readable HTTP citation endpoint for server-generated URLs."""
    document_id = request.path_params.get("document_id", "")
    try:
        _, text = repository.read(document_id)
    except KeyError:
        return JSONResponse({"error": "Markdown document not found"}, status_code=404)
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


class BearerTokenMiddleware:
    """Protect remote HTTP endpoints with a static bearer token.

    The MCP SDK's OAuth implementation is intentionally not enabled here: a
    single-user Valyu connection is best served by a long random bearer token
    stored as a deployment secret.  Leaving MCP_AUTH_TOKEN unset keeps local
    development and stdio usage convenient, but production deployments should
    always set it.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    @staticmethod
    def _header_value(scope: Scope, name: bytes) -> str:
        for key, value in scope.get("headers", []):
            if key.lower() == name.lower():
                return value.decode("latin-1")
        return ""

    def _authorized(self, scope: Scope) -> bool:
        if not AUTH_TOKEN:
            return True

        authorization = self._header_value(scope, b"authorization")
        if authorization.startswith("Bearer "):
            supplied = authorization[7:].strip()
            if supplied == AUTH_TOKEN:
                return True

        # Some MCP clients expose custom header fields more easily than an
        # Authorization header.  This is also useful for manual curl testing.
        supplied_header = self._header_value(scope, b"x-mcp-token")
        if supplied_header == AUTH_TOKEN:
            return True

        if ALLOW_QUERY_TOKEN:
            raw_query = scope.get("query_string", b"").decode("latin-1")
            for item in raw_query.split("&"):
                key, _, value = item.partition("=")
                if key == "token" and value == AUTH_TOKEN:
                    return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/health" or self._authorized(scope):
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


async def _not_found(_: Request) -> JSONResponse:
    return JSONResponse({"error": "Not found"}, status_code=404)


# FastMCP creates its own lifespan for the session manager.  Since both apps
# are mounted below one outer Starlette app, explicitly run that lifespan here
# (nested Starlette lifespans are not propagated through Mount).
streamable_app = mcp.streamable_http_app()
sse_app = mcp.sse_app()


class MCPTransportDispatcher:
    """Dispatch the SDK's two native transports from one root mount."""

    def __init__(self, streamable: Any, sse: Any) -> None:
        self.streamable = streamable
        self.sse = sse

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if path == "/sse" or path == "/messages" or path.startswith("/messages/"):
            await self.sse(scope, receive, send)
        else:
            await self.streamable(scope, receive, send)


transport_app = MCPTransportDispatcher(streamable_app, sse_app)

app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route(
            "/documents/{document_id:path}",
            document_http,
            methods=["GET"],
        ),
        # The dispatcher preserves the SDK's native /mcp, /sse and
        # /messages/ paths while still allowing one outer authentication layer.
        Mount("/", app=transport_app),
        Route("/{path:path}", _not_found),
    ],
    lifespan=lambda _: mcp.session_manager.run(),
)
app = BearerTokenMiddleware(app)


def main() -> None:
    """Run stdio locally or the authenticated HTTP app in deployments."""
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=host, port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
