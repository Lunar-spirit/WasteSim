import time
import uuid

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger("swms")


class RequestContextMiddleware:
    """Stamps every request with a request_id and logs it, in pure ASGI.

    NOT a starlette.middleware.base.BaseHTTPMiddleware subclass on purpose:
    BaseHTTPMiddleware runs the rest of the stack in a separate anyio task so
    it can stream the response, and that task can end up scheduled in a way
    that conflicts with SQLAlchemy's async (asyncpg) driver — surfaces as
    "Future attached to a different loop" under real concurrent load and
    reliably under the test client. Pure ASGI middleware has no such task
    hop: it just forwards scope/receive/send, so it is the version every
    later module's tests will actually run against.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        # Written into scope["state"] (not a Request object — none exists at
        # this layer) so every Request built later from this same scope,
        # anywhere down the stack, sees the same request_id via .state.
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request",
                request_id=request_id,
                method=scope.get("method"),
                path=scope.get("path"),
                status_code=status_code,
                duration_ms=round(duration_ms, 2),
            )
