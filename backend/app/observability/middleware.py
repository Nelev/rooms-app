import logging
import re
import time
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.logs import request_id

logger = logging.getLogger("app.request")

HEADER = "X-Request-ID"
_VALID_ID = re.compile(rb"[A-Za-z0-9._-]{1,128}")


class RequestId:
    """Give each request an ID (the client's X-Request-ID if it is a plain token, else a new one), returned in the
    response's X-Request-ID and on every log line logged while it is handled; log one line per request with its status
    and duration."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        client_id = dict(scope["headers"]).get(HEADER.lower().encode(), b"")
        rid = client_id.decode() if _VALID_ID.fullmatch(client_id) else uuid4().hex
        token = request_id.set(rid)
        start, status = time.perf_counter(), 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info("%s %s %s", scope["method"], scope["path"], status, extra={"status": status, "duration_ms": ms})
            request_id.reset(token)
