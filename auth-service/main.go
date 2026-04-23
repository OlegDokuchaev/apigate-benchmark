package main

import (
	"log"

	"github.com/olegdokuchaev/apigate-example/auth-service/internal/config"
	"github.com/olegdokuchaev/apigate-example/auth-service/internal/security"
	"github.com/olegdokuchaev/apigate-example/auth-service/internal/server"
	"github.com/olegdokuchaev/apigate-example/auth-service/internal/users"
)

func main() {
	cfg := config.Load()
	store := users.NewStore()
	issuer := security.Issuer{Secret: cfg.JWTSecret, TTL: cfg.JWTTTL}
	srv := server.NewServer(server.NewRouter(store, issuer).Handler)

	log.Printf("auth-service listening on %s", cfg.ListenAddr)
	if err := srv.ListenAndServe(cfg.ListenAddr); err != nil {
		log.Fatalf("server: %v", err)
	}
}
