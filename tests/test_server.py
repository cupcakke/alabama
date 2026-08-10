import sys
from pathlib import Path

# Import the repository-local server without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


def test_repository_discovers_markdown_files():
    documents = server.repository.documents()
    assert len(documents) >= 140
    assert all(item.id.endswith(".md") for item in documents)
    assert all(".git" not in item.id.split("/") for item in documents)


def test_search_returns_compatible_results():
    output = server.search("kihallgatas")
    assert output.results
    result = output.results[0]
    assert result.id.endswith(".md")
    assert result.title
    assert result.url.startswith("https://")


def test_fetch_reads_a_document_and_preserves_unicode():
    info = server.repository.documents()[0]
    output = server.fetch(info.id)
    assert output.id == info.id
    assert output.text
    assert output.metadata["source"] == "alabama-markdown-repository"


def test_path_traversal_is_rejected():
    try:
        server.fetch("../server.py")
    except ValueError as exc:
        assert "not found" in str(exc).lower()
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("path traversal unexpectedly succeeded")
