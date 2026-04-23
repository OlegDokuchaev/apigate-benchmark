# auth-service

JWT issuer for the apigate example. The three gateways call `POST /verify` on
every protected request; clients register and log in directly. Storage is
in-memory — a restart drops all users.

Stack: Go 1.23, [`fasthttp`](https://github.com/valyala/fasthttp) +
[`fasthttp/router`](https://github.com/fasthttp/router), HS256 JWTs
(`golang-jwt/jwt/v5`), bcrypt password hashes.

## Endpoints

| Method | Path        | Input                                      | Success response                                                          |
|--------|-------------|--------------------------------------------|---------------------------------------------------------------------------|
| GET    | `/health`   | —                                          | `200 {"status":"ok"}`                                                     |
| POST   | `/register` | `{"email":"…","password":"…"}`             | `201 {"id":"<uuid>","email":"…"}`                                         |
| POST   | `/login`    | `{"email":"…","password":"…"}`             | `200 {"access_token":"<jwt>","token_type":"bearer","expires_in":<sec>}`   |
| POST   | `/verify`   | `Authorization: Bearer <jwt>`              | `200 {"user_id":"<uuid>","email":"…"}`                                    |

Errors are always `{"error": "<message>"}`:

- `400` — malformed JSON, empty email, or password outside 6–128 chars.
- `401` — `/login` with wrong credentials; `/verify` with missing, invalid, or expired token.
- `409` — `/register` when the email is taken.
- `500` — bcrypt or token signing failure.

## Configuration

| Env var           | Default                | Notes                                     |
|-------------------|------------------------|-------------------------------------------|
| `LISTEN_ADDR`     | `:8001`                | fasthttp listen address                   |
| `JWT_SECRET`      | `dev-secret-change-me` | HS256 secret; override in production      |
| `JWT_TTL_MINUTES` | `60`                   | Access token lifetime in minutes          |

Defaults live in `.env.example`.

## Run

```bash
# native
go run .

# docker
docker build -t auth-service .
docker run --rm -p 8001:8001 auth-service
```

Compose from the repo root brings this up alongside `data-service` and the
three gateways.

## Design notes

- **bcrypt stays out of the lock.** `Authenticate` takes an `RLock` only to
  fetch the user, then hashes under no lock at all. A single bcrypt compare
  is ~50 ms; serializing it would cap `/login` throughput at one request per
  core. Safe because `User` is immutable after insert and there is no delete.
- **Register pre-hashes.** `Create` runs bcrypt *before* taking the write
  lock, so duplicate-email races waste one hash. Register is rare compared
  to login, so a short critical section wins.
- **Algorithm pinning.** `jwt.WithValidMethods(["HS256"])` rejects any other
  `alg` header before the keyfunc runs, closing the `alg=none` and
  HS/RS-confusion classes.
- **fasthttp tuning.** `NoDefaultServerHeader` trims a few bytes per response.
  Everything else runs on fasthttp defaults — keepalive on, unlimited
  concurrency.
