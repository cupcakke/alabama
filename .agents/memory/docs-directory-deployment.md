---
name: Markdown MCP document directory
description: The public MCP server's document directory selection and deployment behavior.
---

The server prefers a project-level `docs` directory when it exists and otherwise uses the existing `ribanc` directory, while `DOCS_DIR` can explicitly select another directory.

**Why:** The project already contains its Markdown corpus in `ribanc`, but the external MCP specification conventionally refers to `docs`; this keeps the current corpus available without copying or renaming it.

**How to apply:** Keep the deployment command as `PYTHONPATH=.pythonlibs python3 server.py` and use `DOCS_DIR` only when the deployment's Markdown directory differs from the project defaults.

The deployment target is Autoscale because the MCP endpoint is stateless and does not require an always-on VM.

**Why:** Autoscale is the appropriate production target for a stateless HTTP tool server and avoids selecting a VM deployment unnecessarily.

**How to apply:** Keep `deploymentTarget = "autoscale"` in the deployment configuration unless the service later needs persistent in-memory state or an always-running process.

Python dependencies must be installed during the deployment build into `.pythonlibs`, and the production command must set `PYTHONPATH=.pythonlibs`.

**Why:** This Replit Python runtime may expose `pip` without installing project packages into the active interpreter; relying only on `requirements.txt` or a development-only package directory causes `ModuleNotFoundError` during workflow and deployment startup.

**How to apply:** Keep the build and run commands synchronized in `.replit`, and keep `python313Packages.pip` in `replit.nix`.