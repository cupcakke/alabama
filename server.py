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

REPOSITORY_ROOT = Path(
    os.getenv("MCP_ROOT", str(Path(__file__).resolve().parent))
).expanduser().resolve()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
CITATION_BASE_URL = os.getenv(
    "CITATION_BASE_URL",
    "https://github.com/cupcakke/alabama/blob/main",
).strip().rstrip("/")
MAX_SEARCH_RESULTS = max(1, min(int(os.getenv("MAX_SEARCH_RESULTS", "10")), 50))
MAX_FETCH_CHARS = max(1, int(os.getenv("MAX_FETCH_CHARS", "2000000")))
MAX_SNIPPET_CHARS = max(80, min(int(os.getenv("MAX_SNIPPET_CHARS", "900")), 5000))

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


@dataclass(frozen=True)
class DocumentInfo:
    id: str
    path: Path
    size_bytes: int
    modified_at: str


class MarkdownRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._cache: dict[str, tuple[int, int, str]] = {}
        self._index: dict[str, DocumentInfo] | None = None
        self._index_signature: tuple[int, int] | None = None
        self._lock = threading.RLock()

    def _is_allowed_path(self, path: Path) -> bool:
        if path.is_symlink() or path.suffix.lower() != ".md":
            return False
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return False
        return not any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts)

    def _scan_signature(self) -> tuple[int, int] | None:
        if not self.root.exists():
            return None
        try:
            root_stat = self.root.stat()
        except OSError:
            return None
        return (root_stat.st_mtime_ns, root_stat.st_ino)

    def _rebuild_index(self) -> None:
        found: dict[str, DocumentInfo] = {}
        for path in self.root.rglob("*"):
            if not path.is_file() or not self._is_allowed_path(path):
                continue
            try:
                relative = path.relative_to(self.root).as_posix()
                stat = path.stat()
            except (OSError, ValueError) as exc:
                logger.warning("Skipping unreadable file %s: %s", path, exc)
                continue
            found[relative] = DocumentInfo(
                id=relative,
                path=path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            )
        self._index = found
        self._index_signature = self._scan_signature()

    def documents(self) -> list[DocumentInfo]:
        if not self.root.exists():
            raise RuntimeError(f"MCP_ROOT does not exist: {self.root}")
        signature = self._scan_signature()
        with self._lock:
            if self._index is None or self._index_signature != signature:
                self._rebuild_index()
            return sorted(
                self._index.values(), key=lambda item: item.id.casefold()
            )

    def get(self, document_id: str) -> DocumentInfo:
        if not document_id or "\\" in document_id:
            raise KeyError(document_id)
        try:
            candidate = (self.root / document_id).resolve()
            relative = candidate.relative_to(self.root)
        except (OSError, ValueError):
            raise KeyError(document_id)
        if candidate.is_symlink():
            raise KeyError(document_id)
        if not candidate.is_file() or candidate.suffix.lower() != ".md":
            raise KeyError(document_id)
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
            raise KeyError(document_id)
        try:
            stat = candidate.stat()
        except OSError:
            raise KeyError(document_id)
        return DocumentInfo(
            id=relative.as_posix(),
            path=candidate,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        )

    def read(self, document_id: str) -> tuple[DocumentInfo, str]:
        info = self.get(document_id)
        try:
            stat = info.path.stat()
        except OSError as exc:
            raise KeyError(document_id) from exc

        signature = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._cache.get(info.id)
            if cached is not None and cached[:2] == signature:
                return info, cached[2]

        try:
            text = info.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise KeyError(document_id) from exc

        with self._lock:
            self._cache[info.id] = (signature[0], signature[1], text)
        return info, text


repository = MarkdownRepository(REPOSITORY_ROOT)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def _query_terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[\w\u0080-\uffff]{2,}", _fold(query))]


def _score_document(query: str, info: DocumentInfo, text: str) -> float:
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
            score += min(body_hits, 20) * 1.5

    if terms and all(term in folded_text or term in folded_title for term in terms):
        score += 12.0
    return score


def _snippet(text: str, query: str, max_chars: int = MAX_SNIPPET_CHARS) -> str:
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
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/documents/{quote(document_id, safe='')}"
    return f"{CITATION_BASE_URL}/{quote(document_id, safe='')}"


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
    json_response=False,
    host="0.0.0.0",
    port=int(os.getenv("PORT", "8000")),
)


@mcp.tool()
def search(query: str) -> SearchOutput:
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
        },
        status_code=200 if status == "ok" else 503,
    )


async def document_http(request: Request) -> PlainTextResponse | JSONResponse:
    document_id = request.path_params.get("document_id", "")
    try:
        _, text = repository.read(document_id)
    except KeyError:
        return JSONResponse({"error": "Markdown document not found"}, status_code=404)
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


async def _not_found(_: Request) -> JSONResponse:
    return JSONResponse({"error": "Not found"}, status_code=404)


streamable_app = mcp.streamable_http_app()
sse_app = mcp.sse_app()


class MCPTransportDispatcher:
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
        Mount("/", app=transport_app),
        Route("/{path:path}", _not_found),
    ],
    lifespan=lambda _: mcp.session_manager.run(),
)


def main() -> None:
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
