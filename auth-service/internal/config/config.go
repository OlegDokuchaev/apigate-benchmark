package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	ListenAddr string
	JWTSecret  []byte
	JWTTTL     time.Duration
}

func Load() Config {
	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = ":8001"
	}
	secret := os.Getenv("JWT_SECRET")
	if secret == "" {
		secret = "dev-secret-change-me"
	}
	ttlMin := 60
	if s := os.Getenv("JWT_TTL_MINUTES"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			ttlMin = n
		}
	}
	return Config{
		ListenAddr: addr,
		JWTSecret:  []byte(secret),
		JWTTTL:     time.Duration(ttlMin) * time.Minute,
	}
}
