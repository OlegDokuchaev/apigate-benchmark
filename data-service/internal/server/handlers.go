package server

import (
	"encoding/json"

	"github.com/valyala/fasthttp"

	"github.com/olegdokuchaev/apigate-example/data-service/internal/products"
)

type Handlers struct {
	Store *products.Store
}

type searchInput struct {
	Category *string `json:"category"`
	MaxPrice *int    `json:"max_price"`
}

// lookupInput: the gateway has already rewritten the public `{q}` payload
// into this internal shape. Source is accepted but ignored — it exists so
// the contract remains stable if the store ever starts attributing traffic.
type lookupInput struct {
	Query  string `json:"query"`
	Limit  int    `json:"limit"`
	Source string `json:"source"`
}

func (h *Handlers) Health(ctx *fasthttp.RequestCtx) {
	writeJSON(ctx, fasthttp.StatusOK, map[string]string{"status": "ok"})
}

// GET /items — full catalogue. Baseline for the "simple proxy" scenario.
func (h *Handlers) ListAll(ctx *fasthttp.RequestCtx) {
	writeJSON(ctx, fasthttp.StatusOK, h.Store.All())
}

// GET /my-items — filtered by x-user-id, which the gateway injects after
// verifying the Bearer token. 401 if no gateway is in front.
func (h *Handlers) ListMine(ctx *fasthttp.RequestCtx) {
	uid := string(ctx.Request.Header.Peek("X-User-Id"))
	if uid == "" {
		writeErr(ctx, fasthttp.StatusUnauthorized, "missing X-User-Id")
		return
	}
	writeJSON(ctx, fasthttp.StatusOK, h.Store.ByOwner(uid))
}

// POST /items/search — body already validated by the gateway, passed through.
func (h *Handlers) Search(ctx *fasthttp.RequestCtx) {
	var in searchInput
	if err := json.Unmarshal(ctx.PostBody(), &in); err != nil {
		writeErr(ctx, fasthttp.StatusBadRequest, "invalid json")
		return
	}
	writeJSON(ctx, fasthttp.StatusOK, h.Store.Search(products.SearchFilter{
		Category: in.Category,
		MaxPrice: in.MaxPrice,
	}))
}

// POST /items/lookup — gateway has already rewritten public {q} → {query, limit, source}.
func (h *Handlers) Lookup(ctx *fasthttp.RequestCtx) {
	var in lookupInput
	if err := json.Unmarshal(ctx.PostBody(), &in); err != nil {
		writeErr(ctx, fasthttp.StatusBadRequest, "invalid json")
		return
	}
	writeJSON(ctx, fasthttp.StatusOK, h.Store.Lookup(products.LookupQuery{
		Query: in.Query,
		Limit: in.Limit,
	}))
}
