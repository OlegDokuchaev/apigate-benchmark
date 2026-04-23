package server

import (
	"github.com/fasthttp/router"
	"github.com/valyala/fasthttp"

	"github.com/olegdokuchaev/apigate-example/auth-service/internal/security"
	"github.com/olegdokuchaev/apigate-example/auth-service/internal/users"
)

func NewRouter(store *users.Store, issuer security.Issuer) *router.Router {
	h := &Handlers{Store: store, Issuer: issuer}
	r := router.New()

	r.GET("/health", h.Health)
	r.POST("/register", h.Register)
	r.POST("/login", h.Login)
	r.POST("/verify", h.Verify)

	return r
}

// NewServer wraps a handler in a fasthttp.Server with settings tuned for the
// benchmark: no Server header (saves a few bytes per response) and an explicit
// service name to make hex dumps / tcpdump output easier to read.
func NewServer(handler fasthttp.RequestHandler) *fasthttp.Server {
	return &fasthttp.Server{
		Handler:               handler,
		Name:                  "auth-service",
		NoDefaultServerHeader: true,
	}
}
