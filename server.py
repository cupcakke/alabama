"""Public MCP server for reading and searching Markdown files.

The server exposes the standard Streamable HTTP MCP transport at ``/mcp``.
Markdown files are read from the directory configured by ``DOCS_DIR``.  The
default is the existing ``ribanc`` directory in this project; deployments
that use the conventional ``docs`` directory can set ``DOCS_DIR=docs``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


PROJECT_ROOT = Path(__file__).resolve().parent
CONVENTIONAL_DOCUMENT_DIRECTORY = PROJECT_ROOT / "docs"
EXISTING_DOCUMENT_DIRECTORY = PROJECT_ROOT / "ribanc"
DEFAULT_DOCUMENT_DIRECTORY = (
    CONVENTIONAL_DOCUMENT_DIRECTORY
    if CONVENTIONAL_DOCUMENT_DIRECTORY.is_dir()
    else EXISTING_DOCUMENT_DIRECTORY
)
DOCUMENT_DIRECTORY = Path(
    os.environ.get("DOCS_DIR", str(DEFAULT_DOCUMENT_DIRECTORY))
).expanduser()
if not DOCUMENT_DIRECTORY.is_absolute():
    DOCUMENT_DIRECTORY = PROJECT_ROOT / DOCUMENT_DIRECTORY
DOCUMENT_DIRECTORY = DOCUMENT_DIRECTORY.resolve()

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))

mcp = FastMCP(
    "Markdown Documentation",
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _ensure_document_directory() -> None:
    """Raise a clear error when the configured Markdown directory is absent."""
    if not DOCUMENT_DIRECTORY.is_dir():
        raise FileNotFoundError(
            f"Markdown directory does not exist: {DOCUMENT_DIRECTORY}"
        )


def _markdown_files() -> list[Path]:
    """Return all Markdown files below the document directory in stable order."""
    _ensure_document_directory()
    files: list[Path] = []
    for path in DOCUMENT_DIRECTORY.rglob("*.md"):
        if not path.is_file():
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(DOCUMENT_DIRECTORY)
        except ValueError:
            continue
        files.append(resolved_path)
    return sorted(files, key=_relative_filename)


def _relative_filename(path: Path) -> str:
    """Return a portable, user-facing path relative to the document directory."""
    return path.relative_to(DOCUMENT_DIRECTORY).as_posix()


def _resolve_filename(filename: str) -> Path:
    """Resolve a relative Markdown filename without permitting path traversal."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("filename must be a non-empty string")

    requested = Path(filename)
    if requested.is_absolute():
        raise ValueError("filename must be relative to the Markdown directory")

    candidate = (DOCUMENT_DIRECTORY / requested).resolve()
    try:
        candidate.relative_to(DOCUMENT_DIRECTORY)
    except ValueError as exc:
        raise ValueError("filename must remain inside the Markdown directory") from exc

    if candidate.suffix.lower() != ".md":
        raise ValueError("filename must identify a .md file")
    if not candidate.is_file():
        raise FileNotFoundError(f"Markdown file not found: {filename}")
    return candidate


@mcp.tool()
def list_markdown_files() -> dict[str, Any]:
    """List every available Markdown filename in the configured directory.

    The directory is scanned at call time.  Nested Markdown files are included,
    and filenames use forward slashes so the result is portable across systems.
    """
    files = _markdown_files()
    return {
        "directory": str(DOCUMENT_DIRECTORY),
        "files": [_relative_filename(path) for path in files],
        "total_files": len(files),
    }


@mcp.tool()
def read_markdown_file(filename: str) -> dict[str, Any]:
    """Return the complete UTF-8 contents of one Markdown file exactly as stored.

    ``filename`` must be a relative path returned by ``list_markdown_files``.
    The content is not summarized, transformed, sanitized, or truncated.
    """
    path = _resolve_filename(filename)
    try:
        with path.open("r", encoding="utf-8", newline="") as document:
            content = document.read()
    except UnicodeDecodeError as exc:
        raise ValueError(f"Markdown file is not valid UTF-8: {filename}") from exc
    except OSError as exc:
        raise RuntimeError(f"Unable to read Markdown file: {filename}") from exc

    return {
        "filename": _relative_filename(path),
        "content": content,
    }


@mcp.tool()
def search_markdown(
    query: str,
    case_sensitive: bool = False,
    context_lines: int = 1,
) -> dict[str, Any]:
    """Search every Markdown file for every literal matching line.

    ``query`` is matched literally rather than as a regular expression.
    Matching is performed line by line.  Every matching line includes its
    one-based line number, exact line text, and the requested surrounding
    context.  Results are deterministic and include every occurrence in every
    matching file.
    """
    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string")
    if not isinstance(case_sensitive, bool):
        raise ValueError("case_sensitive must be a boolean")
    if not isinstance(context_lines, int) or isinstance(context_lines, bool):
        raise ValueError("context_lines must be an integer")
    if context_lines < 0:
        raise ValueError("context_lines must be greater than or equal to zero")

    comparison_query = query if case_sensitive else query.casefold()
    results: dict[str, dict[str, Any]] = {}
    total_matches = 0

    for path in _markdown_files():
        filename = _relative_filename(path)
        try:
            with path.open("r", encoding="utf-8", newline="") as document:
                content = document.read()
        except UnicodeDecodeError as exc:
            raise ValueError(f"Markdown file is not valid UTF-8: {filename}") from exc
        except OSError as exc:
            raise RuntimeError(f"Unable to read Markdown file: {filename}") from exc

        lines = content.splitlines()
        matches: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            comparison_line = line if case_sensitive else line.casefold()
            if comparison_query not in comparison_line:
                continue

            first_context_line = max(0, index - context_lines)
            last_context_line = min(len(lines), index + context_lines + 1)
            context = [
                {
                    "line_number": context_index + 1,
                    "line": lines[context_index],
                }
                for context_index in range(first_context_line, last_context_line)
            ]
            matches.append(
                {
                    "line_number": index + 1,
                    "match_line": line,
                    "context": context,
                }
            )

        if matches:
            results[filename] = {
                "match_count": len(matches),
                "matches": matches,
            }
            total_matches += len(matches)

    return {
        "query": query,
        "case_sensitive": case_sensitive,
        "context_lines": context_lines,
        "total_files_matched": len(results),
        "total_matches": total_matches,
        "results": results,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")