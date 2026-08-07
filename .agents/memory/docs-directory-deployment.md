---
name: Markdown MCP document directory
description: The public MCP server's document directory selection and deployment behavior.
---

The server prefers a project-level `docs` directory when it exists and otherwise uses the existing `ribanc` directory, while `DOCS_DIR` can explicitly select another directory.

**Why:** The project already contains its Markdown corpus in `ribanc`, but the external MCP specification conventionally refers to `docs`; this keeps the current corpus available without copying or renaming it.

**How to apply:** Keep the deployment command as `PYTHONPATH=.pythonlibs python3 server.py` and use `DOCS_DIR` only when the deployment's Markdown directory differs from the project defaults.