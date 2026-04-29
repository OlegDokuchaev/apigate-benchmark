import socket
from typing import Any

import aiohttp
import msgspec

from .auth_client import AuthClient, AuthError
from .common import (
    ASGIApp,
    ASGIReceive,
    ASGIScope,
    ASGISend,
    END_BODY_MESSAGE,
    ClientDisconnected,
    extract_authorization,
    read_body,
    request_headers_for_upstream,
    response_headers_from_upstream,
    send_error,
)
from .schemas import LookupInput, LookupInternal, SearchInput
from .settings import settings

# ---- msgspec singletons (reuse internal buffers across requests) ----
_search_decoder: msgspec.json.Decoder[SearchInput] = msgspec.json.Decoder(type=SearchInput)
_lookup_decoder: msgspec.json.Decoder[LookupInput] = msgspec.json.Decoder(type=LookupInput)
_lookup_encoder: msgspec.json.Encoder = msgspec.json.Encoder()

_ITEMS_URL: str = f"{settings.ORIGIN_BASE_URL}/items"
_MY_ITEMS_URL: str = f"{settings.ORIGIN_BASE_URL}/my-items"
_SEARCH_URL: str = f"{settings.ORIGIN_BASE_URL}/items/search"
_LOOKUP_URL: str = f"{settings.ORIGIN_BASE_URL}/items/lookup"

_GATEWAY_SOURCE: str = "gateway"
_LOOKUP_LIMIT: int = 20


def _build_upstream_timeout() -> aiohttp.ClientTimeout:
    # sock_read=None because upstream responses are streamed back to the client;
    # a per-socket-read deadline would wrongly abort a slow-but-valid chunked body.
    # The total=UPSTREAM_TOTAL_TIMEOUT still caps the whole exchange.
    return aiohttp.ClientTimeout(
        total=settings.UPSTREAM_TOTAL_TIMEOUT,
        connect=settings.UPSTREAM_CONNECT_TIMEOUT,
        sock_connect=settings.UPSTREAM_CONNECT_TIMEOUT,
        sock_read=None,
    )


def _build_auth_timeout() -> aiohttp.ClientTimeout:
    # Unlike the proxy path, /verify is a single non-streaming request, so
    # capping per-socket-read is safe and catches hung auth upstreams faster.
    return aiohttp.ClientTimeout(
        total=settings.AUTH_TOTAL_TIMEOUT,
        connect=settings.AUTH_CONNECT_TIMEOUT,
        sock_connect=settings.AUTH_CONNECT_TIMEOUT,
        sock_read=settings.AUTH_TOTAL_TIMEOUT,
    )


def _set_tcp_option(sock: socket.socket, name: str, value: int) -> None:
    option = getattr(socket, name, None)
    if option is not None:
        sock.setsockopt(socket.IPPROTO_TCP, option, value)


def _tcp_socket_factory(addr_info: tuple[Any, ...]) -> socket.socket:
    family, type_, proto, _, _ = addr_info
    sock = socket.socket(family=family, type=type_, proto=proto)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        _set_tcp_option(sock, "TCP_KEEPIDLE", settings.AIOHTTP_TCP_KEEPALIVE_IDLE)
    else:
        _set_tcp_option(sock, "TCP_KEEPALIVE", settings.AIOHTTP_TCP_KEEPALIVE_IDLE)
    return sock


def _build_session() -> aiohttp.ClientSession:
    # auto_decompress=False — we are a transparent proxy; decompressing would
    # force us to re-encode and lie about content-encoding/length to the client.
    # raise_for_status=False — upstream 4xx/5xx are forwarded to the client
    # verbatim, not turned into aiohttp exceptions.
    # keepalive_timeout — keep idle pooled sockets alive across k6 profile
    # phases; default 15s is too short.
    # enable_cleanup_closed — reaper for sockets the kernel has half-closed
    # under bursty ramps; without it FDs leak until the next gc cycle.
    return aiohttp.ClientSession(
        timeout=_build_upstream_timeout(),
        connector=aiohttp.TCPConnector(
            limit=settings.AIOHTTP_CONNECTOR_LIMIT,
            limit_per_host=settings.AIOHTTP_LIMIT_PER_HOST,
            keepalive_timeout=settings.AIOHTTP_KEEPALIVE_TIMEOUT,
            socket_factory=_tcp_socket_factory,
            use_dns_cache=True,
            ttl_dns_cache=settings.AIOHTTP_DNS_TTL,
            enable_cleanup_closed=True,
        ),
        auto_decompress=False,
        raise_for_status=False,
    )


async def _relay_response(send: ASGISend, response: aiohttp.ClientResponse) -> None:
    await send({
        "type": "http.response.start",
        "status": response.status,
        "headers": response_headers_from_upstream(response.raw_headers),
    })
    # Status line has already left; mid-stream upstream errors must NOT trigger
    # a fresh `http.response.start` via send_error — just close the body.
    try:
        async for chunk in response.content.iter_any():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
    except aiohttp.ClientError:
        pass
    await send(END_BODY_MESSAGE)


# 1) baseline — bare proxy, no hooks
async def handle_items(
    scope: ASGIScope,
    send: ASGISend,
    session: aiohttp.ClientSession,
) -> None:
    async with session.request(
        "GET",
        _ITEMS_URL,
        headers=request_headers_for_upstream(scope),
        allow_redirects=False,
    ) as upstream:
        await _relay_response(send, upstream)


# 2) verify bearer token, inject x-user-id/x-user-email, strip Authorization
async def handle_my_items(
    scope: ASGIScope,
    send: ASGISend,
    session: aiohttp.ClientSession,
    auth: AuthClient,
) -> None:
    authorization = extract_authorization(scope)
    if authorization is None:
        await send_error(send, 401, "missing authorization")
        return

    try:
        user = await auth.verify(authorization)
    except AuthError as exc:
        await send_error(send, exc.status, str(exc))
        return

    headers = request_headers_for_upstream(scope, drop_authorization=True)
    headers["x-user-id"] = user.user_id
    headers["x-user-email"] = user.email

    async with session.request(
        "GET",
        _MY_ITEMS_URL,
        headers=headers,
        allow_redirects=False,
    ) as upstream:
        await _relay_response(send, upstream)


# 3) typed body validation, forward body as-is
async def handle_search(
    scope: ASGIScope,
    receive: ASGIReceive,
    send: ASGISend,
    session: aiohttp.ClientSession,
) -> None:
    body = await read_body(receive)
    try:
        _search_decoder.decode(body)
    except (msgspec.ValidationError, msgspec.DecodeError) as exc:
        await send_error(send, 400, str(exc))
        return

    async with session.request(
        "POST",
        _SEARCH_URL,
        headers=request_headers_for_upstream(scope),
        data=body,
        allow_redirects=False,
    ) as upstream:
        await _relay_response(send, upstream)


# 4) validate public body and rewrite to internal schema before forwarding
async def handle_lookup(
    scope: ASGIScope,
    receive: ASGIReceive,
    send: ASGISend,
    session: aiohttp.ClientSession,
) -> None:
    body = await read_body(receive)
    try:
        payload = _lookup_decoder.decode(body)
    except (msgspec.ValidationError, msgspec.DecodeError) as exc:
        await send_error(send, 400, str(exc))
        return

    new_body = _lookup_encoder.encode(LookupInternal(
        query=payload.q.strip(),
        limit=_LOOKUP_LIMIT,
        source=_GATEWAY_SOURCE,
    ))
    async with session.request(
        "POST",
        _LOOKUP_URL,
        headers=request_headers_for_upstream(scope),
        data=new_body,
        allow_redirects=False,
    ) as upstream:
        await _relay_response(send, upstream)


# ---- ASGI wiring ---------------------------------------------------------

class _AppState:
    __slots__ = ("session", "auth")

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self.auth: AuthClient | None = None


async def _handle_lifespan(
    receive: ASGIReceive,
    send: ASGISend,
    state: _AppState,
) -> None:
    while True:
        message = await receive()
        mt = message["type"]
        if mt == "lifespan.startup":
            state.session = _build_session()
            state.auth = AuthClient(
                session=state.session,
                verify_url=settings.AUTH_VERIFY_URL,
                timeout=_build_auth_timeout(),
            )
            await send({"type": "lifespan.startup.complete"})
        elif mt == "lifespan.shutdown":
            session = state.session
            if session is not None and not session.closed:
                await session.close()
            state.session = None
            state.auth = None
            await send({"type": "lifespan.shutdown.complete"})
            return


def main() -> ASGIApp:
    state = _AppState()

    async def asgi_app(scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        scope_type = scope["type"]

        if scope_type == "lifespan":
            await _handle_lifespan(receive, send, state)
            return

        if scope_type != "http":
            return

        session = state.session
        auth = state.auth
        if session is None or auth is None:
            await send_error(send, 503, "gateway not ready")
            return

        method = scope["method"]
        path = scope["path"]

        try:
            if method == "GET":
                if path == "/items":
                    await handle_items(scope, send, session)
                    return
                if path == "/my-items":
                    await handle_my_items(scope, send, session, auth)
                    return
            elif method == "POST":
                if path == "/items/search":
                    await handle_search(scope, receive, send, session)
                    return
                if path == "/items/lookup":
                    await handle_lookup(scope, receive, send, session)
                    return
            await send_error(send, 404, f"unknown route: {method} {path}")
        except ClientDisconnected:
            return
        except aiohttp.ClientError as exc:
            await send_error(send, 502, f"upstream client error: {exc}")
        except TimeoutError:
            await send_error(send, 504, "upstream timeout")

    return asgi_app


app = main()
