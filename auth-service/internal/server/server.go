package server

import (
	"time"

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
// benchmark and basic production hygiene:
//   - no Server header / explicit Name — smaller responses, easier tcpdump.
//   - Read/WriteTimeout — bound a single request so a slow client cannot pin
//     a worker forever (fasthttp default is 0 = infinite).
//   - IdleTimeout — close idle keep-alive sockets at 120s, matching the
//     gateways' upstream pool_idle_timeout (apigate / kong / python all 120s).
//     Without parity, one side closes first and the other pays an unnecessary
//     reconnect on the next request.
//   - TCPKeepalive — let the kernel detect half-open clients (gateway crashes,
//     network blips) instead of waiting for the OS connection-tracking timeout.
func NewServer(handler fasthttp.RequestHandler) *fasthttp.Server {
	return &fasthttp.Server{
		Handler:               handler,
		Name:                  "auth-service",
		NoDefaultServerHeader: true,
		ReadTimeout:           10 * time.Second,
		WriteTimeout:          10 * time.Second,
		IdleTimeout:           120 * time.Second,
		TCPKeepalive:          true,
		TCPKeepalivePeriod:    30 * time.Second,
	}
}
