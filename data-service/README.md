# data-service

Product catalogue for the apigate example. It is the upstream for all three
gateways and has no notion of JWTs — it trusts the `X-User-Id` header the
gateway injects after verifying a token.

Stack: Go 1.23, [`fasthttp`](https://github.com/valyala/fasthttp) +
[`fasthttp/router`](https://github.com/fasthttp/router). Storage is a hardcoded
7-item slice seeded at start.

## Endpoints

| Method | Path             | Input                                         | Success response                       |
|--------|------------------|-----------------------------------------------|----------------------------------------|
| GET    | `/health`        | —                                             | `200 {"status":"ok"}`                  |
| GET    | `/items`         | —                                             | `200 [<product>, …]` — full catalogue  |
| GET    | `/my-items`      | `X-User-Id: <uuid>`                           | `200 [<product>, …]` — filtered by owner |
| POST   | `/items/search`  | `{"category"?: string, "max_price"?: int}`    | `200 [<product>, …]`                   |
| POST   | `/items/lookup`  | `{"query": string, "limit": int, "source": string}` | `200 [<product>, …]`            |

`<product>`: `{"id", "owner_id", "name", "price", "category"}`. Empty results
are returned as `[]`, never `null`.

Error envelope is always `{"error": "<message>"}`:

- `400` — malformed JSON on `/items/search` or `/items/lookup`.
- `401` — `/my-items` called without `X-User-Id` (no gateway in front).

## Contract boundaries

`/items/lookup` accepts the internal shape only. The public `{q}` → internal
`{query, limit, source}` rewrite happens in the gateway. `source` is accepted
and ignored — it stays in the schema so the contract remains stable if the
service ever starts attributing traffic.

`/my-items` requires `X-User-Id` but does **not** verify it. The gateway is
responsible for setting it from a verified JWT and stripping any caller-supplied
value. Running the service without a gateway in front is a security hole.

## Configuration

| Env var       | Default | Notes                    |
|---------------|---------|--------------------------|
| `LISTEN_ADDR` | `:8002` | fasthttp listen address  |

## Run

```bash
# native
go run .

# docker
docker build -t data-service .
docker run --rm -p 8002:8002 data-service
```

Compose from the repo root brings this up alongside `auth-service` and the
three gateways.

## Design notes

- **Immutable catalogue, pre-indexed.** `NewStore()` builds
  `ownerIndex map[string][]Product` and `lowerNames []string` once.
  `/my-items` becomes a single map lookup; `/items/lookup` does
  `strings.Contains` against precomputed lowercase names instead of calling
  `strings.ToLower(p.Name)` per product per request.
- **Shared slices.** `All()` and `ByOwner()` return slices backed by the
  store itself — handlers only marshal, never mutate. Saves a copy on the
  hot paths.
- **Empty ≠ nil.** Non-matching filters return a shared `[]Product{}` so JSON
  marshals as `[]` rather than `null`.
- **fasthttp tuning.** `NoDefaultServerHeader` trims a few bytes per response.
  Everything else runs on fasthttp defaults.
