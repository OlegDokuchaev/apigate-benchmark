package server

import (
	"github.com/fasthttp/router"
	"github.com/valyala/fasthttp"

	"github.com/olegdokuchaev/apigate-example/data-service/internal/products"
)

func NewRouter(store *products.Store) *router.Router {
	h := &Handlers{Store: store}
	r := router.New()

	r.GET("/health", h.Health)

	r.GET("/items", h.ListAll)
	r.GET("/my-items", h.ListMine)
	r.POST("/items/search", h.Search)
	r.POST("/items/lookup", h.Lookup)

	return r
}

// NewServer wraps a handler in a fasthttp.Server with benchmark-oriented
// defaults: no Server header (smaller responses), explicit service name.
func NewServer(handler fasthttp.RequestHandler) *fasthttp.Server {
	return &fasthttp.Server{
		Handler:               handler,
		Name:                  "data-service",
		NoDefaultServerHeader: true,
	}
}
