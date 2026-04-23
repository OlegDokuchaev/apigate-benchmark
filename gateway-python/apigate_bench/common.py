from typing import Any, Awaitable, Callable, Iterable

import msgspec
from multidict import CIMultiDict

ASGIScope = dict[str, Any]
ASGIMessage = dict[str, Any]
ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
ASGISend = Callable[[ASGIMessage], Awaitable[None]]
ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]
HeaderList = list[tuple[bytes, bytes]]
HeadersIterable = Iterable[tuple[bytes, bytes]]

HOP_BY_HOP_HEADERS: frozenset[bytes] = frozenset({
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
})

END_BODY_MESSAGE: ASGIMessage = {
    "type": "http.response.body",
    "body": b"",
    "more_body": False,
}


class ClientDisconnected(Exception):
    pass


async def read_body(receive: ASGIReceive, *, limit: int) -> bytes:
    while True:
        message = await receive()
        msg_type = message["type"]
        if msg_type == "http.disconnect":
            raise ClientDisconnected("client disconnected while sending request body")
        if msg_type == "http.request":
            break

    first_chunk: bytes = message.get("body", b"")
    if not message.get("more_body", False):
        # Fast path: entire body arrived in a single http.request message.
        if len(first_chunk) > limit:
            raise ValueError(f"request body exceeds limit {limit} bytes")
        return first_chunk

    total = len(first_chunk)
    if total > limit:
        raise ValueError(f"request body exceeds limit {limit} bytes")
    chunks: list[bytes] = [first_chunk] if first_chunk else []
    while True:
        message = await receive()
        msg_type = message["type"]
        if msg_type == "http.disconnect":
            raise ClientDisconnected("client disconnected while sending request body")
        if msg_type != "http.request":
            continue
        chunk = message.get("body", b"")
        if chunk:
            total += len(chunk)
            if total > limit:
                raise ValueError(f"request body exceeds limit {limit} bytes")
            chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


async def send_json(
    send: ASGISend,
    status: int,
    payload: Any,
    headers: HeadersIterable | None = None,
) -> None:
    body = msgspec.json.encode(payload)
    final_headers: HeaderList = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if headers:
        final_headers.extend(headers)
    await send({"type": "http.response.start", "status": status, "headers": final_headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def send_error(send: ASGISend, status: int, detail: str) -> None:
    await send_json(send, status, {"error": detail})


def request_headers_for_upstream(
    scope: ASGIScope, *, drop_authorization: bool = False
) -> CIMultiDict[str]:
    # ASGI 3.0 guarantees header names are already lowercased bytes, so we
    # skip .lower() here. latin-1 is the canonical 1:1 byte<->codepoint
    # mapping for HTTP header values (RFC 9110 allows ASCII/obsolete text).
    headers: CIMultiDict[str] = CIMultiDict()
    for key, value in scope["headers"]:
        if key in HOP_BY_HOP_HEADERS or key == b"host" or key == b"content-length":
            continue
        if drop_authorization and key == b"authorization":
            continue
        headers.add(key.decode("latin-1"), value.decode("latin-1"))
    return headers


def response_headers_from_upstream(raw_headers: Iterable[tuple[bytes, bytes]]) -> HeaderList:
    result: HeaderList = []
    for key, value in raw_headers:
        if key.lower() in HOP_BY_HOP_HEADERS:
            continue
        result.append((key, value))
    return result


def extract_authorization(scope: ASGIScope) -> str | None:
    for key, value in scope["headers"]:
        if key == b"authorization":
            return value.decode("latin-1")
    return None
