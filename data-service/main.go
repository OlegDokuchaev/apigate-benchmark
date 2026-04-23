package main

import (
	"log"
	"os"

	"github.com/olegdokuchaev/apigate-example/data-service/internal/products"
	"github.com/olegdokuchaev/apigate-example/data-service/internal/server"
)

func main() {
	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = ":8002"
	}

	store := products.NewStore()
	srv := server.NewServer(server.NewRouter(store).Handler)

	log.Printf("data-service listening on %s", addr)
	if err := srv.ListenAndServe(addr); err != nil {
		log.Fatalf("server: %v", err)
	}
}
