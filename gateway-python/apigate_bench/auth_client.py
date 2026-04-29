import asyncio

import aiohttp
import msgspec

from .schemas import VerifyOut


_verify_decoder: msgspec.json.Decoder[VerifyOut] = msgspec.json.Decoder(type=VerifyOut)


class AuthError(Exception):
    """Raised when auth-service /verify does not yield a valid identity.

    `status` is the HTTP code the gateway should return to the caller.
    """

    __slots__ = ("status",)

    def __init__(self, status: int, detail: str | None = None) -> None:
        self.status = status
        super().__init__(detail or f"auth error: {status}")


class AuthClient:
    """Thin wrapper around POST /verify on auth-service.

    Every call hits the upstream — no caching, no request deduplication — so
    the comparison against the Rust apigate and Kong gateways stays apples to
    apples. The only shared infrastructure is the keep-alive
    `aiohttp.ClientSession`, which all three implementations use as well.
    """

    __slots__ = ("_session", "_verify_url", "_timeout")

    def __init__(
        self,
        session: aiohttp.ClientSession,
        verify_url: str,
        timeout: aiohttp.ClientTimeout,
    ) -> None:
        self._session = session
        self._verify_url = verify_url
        self._timeout = timeout

    async def verify(self, authorization: str) -> VerifyOut:
        try:
            async with self._session.post(
                self._verify_url,
                headers={"Authorization": authorization},
                timeout=self._timeout,
            ) as resp:
                if resp.status != 200:
                    raise AuthError(401, "invalid or expired token")
                raw = await resp.read()
        except asyncio.TimeoutError as exc:
            raise AuthError(401, "auth verify failed: timeout") from exc
        except aiohttp.ClientError as exc:
            raise AuthError(401, f"auth verify failed: {exc}") from exc

        try:
            return _verify_decoder.decode(raw)
        except (msgspec.ValidationError, msgspec.DecodeError) as exc:
            raise AuthError(401, "bad verify response") from exc
