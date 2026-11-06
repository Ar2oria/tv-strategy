"""Buffered ASGI request-body limiting based on actual received bytes."""

from app.api.errors import public_error_response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyTooLarge(Exception):
    """The actual streamed request body crossed the configured byte boundary."""


class RequestBodyLimitMiddleware:
    """Bound buffering for every route, including routes that ignore bodies."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("Request body limit must be positive")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            messages = await self._receive_bounded(receive)
        except RequestBodyTooLarge:
            response = public_error_response(
                scope["path"],
                code="request_too_large",
                message="Request is too large",
                status_code=413,
                headers={"Connection": "close"},
            )
            await response(scope, receive, send)
            return

        buffered = iter(messages)

        async def replay() -> Message:
            try:
                return next(buffered)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)

    async def _receive_bounded(self, receive: Receive) -> tuple[Message, ...]:
        messages: list[Message] = []
        received_bytes = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                return tuple(messages)
            if message["type"] != "http.request":
                continue
            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_bytes:
                raise RequestBodyTooLarge()
            if not message.get("more_body", False):
                return tuple(messages)
