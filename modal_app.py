from pathlib import Path

import modal


APP_NAME = "alabama-markdown-mcp"
REPOSITORY_ROOT = Path(__file__).resolve().parent

image = (
    modal.Image.debian_slim(python_version="3.11")
    .uv_pip_install(
        "mcp>=1.28,<2",
        "uvicorn[standard]>=0.30,<1",
    )
    .add_local_dir(
        REPOSITORY_ROOT,
        remote_path="/app",
        copy=True,
        ignore=[
            ".git",
            ".git/**",
            ".venv",
            ".venv/**",
            "venv",
            "venv/**",
            "__pycache__",
            "__pycache__/**",
            ".pytest_cache",
            ".pytest_cache/**",
            ".mypy_cache",
            ".mypy_cache/**",
            ".ruff_cache",
            ".ruff_cache/**",
            "*.pyc",
            ".env",
        ],
    )
)

app = modal.App(APP_NAME)


@app.function(
    image=image,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def web():
    import sys

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    from server import app as mcp_app

    return mcp_app
