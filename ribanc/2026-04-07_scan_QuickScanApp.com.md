import os
import re
import base64
import json
import uuid
import asyncio
import logging
import time
import subprocess
import urllib.parse
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
import httpx
import asyncpg
from pydantic import BaseModel, field_validator
from typing import Optional
from replit.object_storage import Client as ObjClient
from flymyai import client as FlyMyAIClient, FlyMyAIPredictException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

MAX_SESSIONS = 500
SESSION_TTL = 21600
DELETED_SESSION_TTL = SESSION_TTL
MAX_TOOL_ITERATIONS = 200
MAX_HISTORY_MESSAGES = 60
MAX_STORED_MESSAGES = MAX_HISTORY_MESSAGES * 2
MAX_SUMMARY_CHARS = 600
EXA_NUM_RESULTS = 100
MAX_MODEL_CONTENT_CHARS = 200000
MAX_DELETED_SESSIONS = 1000
MAX_MESSAGE_LENGTH = 100000
MAX_PROMPT_LENGTH = 10000
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_DB_INLINE_IMAGE_BYTES = 512 * 1024
MAX_EXA_CONCURRENT = 3
EXA_QPS_LIMIT = 8

---

MAX_IMAGE_CONCURRENT = 20
ALLOWED_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_REFERENCE_IMAGES = 13
DEEP_SEARCH_TYPES = {"deep", "deep-reasoning"}
DB_URL = "postgresql://{}:{}@{}:/{}".format(
urllib.parse.quote(os.getenv("DB_USERNAME", "postgres"), safe=""),
urllib.parse.quote(os.getenv("DB_PASSWORD", ""), safe=""),
os.getenv("DB_HOST", "helium"),
os.getenv("DB_PORT", "5432"),
os.getenv("DB_DATABASE", "heliumdb"),
)
OBJ_BUCKET = os.getenv("OBJ_BUCKET", "")
IMAGE_REF_DELIM = "|||"

_FRIENDLI_TOKEN = os.getenv("FRIENDLI_TOKEN", "")
_EXA_API_KEY = os.getenv("EXA_API_KEY", "")
_XAI_API_KEY = os.getenv("XAI_API_KEY", "")
_FIREWORKS_API_KEY = os.getenv("FIREWORKS_API_KEY", "")
_FLYMYAI_KEY = os.getenv("FLYMYAI_API_KEY", "")
XAI_VIDEO_BASE = "https://api.x.ai/v1"
XAI_VIDEO_POLL_INTERVAL = 5
XAI_VIDEO_TIMEOUT = 300
ALLOWED_VIDEO_DURATIONS = {"6", "10"}
ALLOWED_VIDEO_RESOLUTIONS = {"480p", "720p"}
_video_requests: dict[str, dict] = {}

import collections

class AsyncRateLimiter:
    def __init__(self, max_per_second: int):
        self._max = max_per_second
        self._interval = 1.0 / max_per_second
        self._timestamps: collections.deque = collections.deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= 1.0:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max:
                    self._timestamps.append(time.monotonic())

---

return
wait = 1.0 - (now - self._timestamps[0]) + 0.05
if wait > 0:
await asyncio.sleep(wait)

_exa_limiter = AsyncRateLimiter(EXA_QPS_LIMIT)

sessions: dict[str, dict] = {}
sessions_lock = asyncio.Lock()
_session_locks: dict[str, asyncio.Lock] = {}
_deleted_sessions: dict[str, float] = {}
_deleted_sessions_lock = asyncio.Lock()
_ai_client: AsyncOpenAI | None = None
_agent_client: AsyncOpenAI | None = None
_http_client: httpx.AsyncClient | None = None
_db_pool: asyncpg.Pool | None = None
_obj_client: ObjClient | None = None
_fma_client = None
_executor_semaphore = asyncio.Semaphore(MAX_IMAGE_CONCURRENT)

MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
EXT_TO_MIME = {v: k for k, v in MIME_TO_EXT.items()}

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(PROJECT_ROOT, "index.html")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
STATIC_SW_FILE = os.path.join(STATIC_DIR, "sw.js")

def _get_session_lock(sid: str) -> asyncio.Lock:
    if sid not in _session_locks:
        _session_locks[sid] = asyncio.Lock()
    return _session_locks[sid]

def _prune_deleted_sessions_unlocked(now: Optional[float] = None) -> None:
    ts_now = now if now is not None else time.time()
    expired = [
        sid for sid, deleted_at in list(_deleted_sessions.items())
if ts_now - deleted_at > DELETED_SESSION_TTL
]
for sid in expired:
  _deleted_sessions.pop(sid, None)
if len(_deleted_sessions) > MAX_DELETED_SESSIONS:
  oldest = sorted(_deleted_sessions.items(), key=lambda x: x[1])
  for sid, _ in oldest[: len(_deleted_sessions) - MAX_DELETED_SESSIONS]:
    _deleted_sessions.pop(sid, None)


def _is_deleted(sid: str) -> bool:
  deleted_at = _deleted_sessions.get(sid)
  if deleted_at is None:
    return False
  if time.time() - deleted_at > DELETED_SESSION_TTL:
    return False
  return True


async def _mark_deleted(sid: str) -> None:
  async with _deleted_sessions_lock:
    _prune_deleted_sessions_unlocked()
    _deleted_sessions[sid] = time.time()
    _prune_deleted_sessions_unlocked()


async def _unmark_deleted(sid: str) -> None:
  async with _deleted_sessions_lock:
    _deleted_sessions.pop(sid, None)
    _prune_deleted_sessions_unlocked()


def _detect_image_format(data: bytes) -> tuple[str, str]:
  if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
    return "image/png", ".png"
  if len(data) >= 2 and data[:2] == b"\xff\xd8":
    return "image/jpeg", ".jpg"
  if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
    return "image/webp", ".webp"
  if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
    return "image/gif", ".gif"
  return "application/octet-stream", ""

---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---



---

