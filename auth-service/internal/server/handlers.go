package server

import (
	"bytes"
	"encoding/json"
	"errors"

	"github.com/valyala/fasthttp"

	"github.com/olegdokuchaev/apigate-example/auth-service/internal/security"
	"github.com/olegdokuchaev/apigate-example/auth-service/internal/users"
)

type Handlers struct {
	Store  *users.Store
	Issuer security.Issuer
}

type credentials struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type registerResponse struct {
	ID    string `json:"id"`
	Email string `json:"email"`
}

type loginResponse struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
	ExpiresIn   int    `json:"expires_in"`
}

type verifyResponse struct {
	UserID string `json:"user_id"`
	Email  string `json:"email"`
}

// bearerPrefix is reused to avoid allocating on every /verify call.
var bearerPrefix = []byte("Bearer ")

func (h *Handlers) Health(ctx *fasthttp.RequestCtx) {
	writeJSON(ctx, fasthttp.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handlers) Register(ctx *fasthttp.RequestCtx) {
	var in credentials
	if err := json.Unmarshal(ctx.PostBody(), &in); err != nil {
		writeErr(ctx, fasthttp.StatusBadRequest, "invalid json")
		return
	}
	if in.Email == "" || len(in.Password) < 6 || len(in.Password) > 128 {
		writeErr(ctx, fasthttp.StatusBadRequest, "invalid payload")
		return
	}
	u, err := h.Store.Create(in.Email, in.Password)
	if errors.Is(err, users.ErrEmailTaken) {
		writeErr(ctx, fasthttp.StatusConflict, "email already registered")
		return
	}
	if err != nil {
		writeErr(ctx, fasthttp.StatusInternalServerError, "internal error")
		return
	}
	writeJSON(ctx, fasthttp.StatusCreated, registerResponse{ID: u.ID, Email: u.Email})
}

func (h *Handlers) Login(ctx *fasthttp.RequestCtx) {
	var in credentials
	if err := json.Unmarshal(ctx.PostBody(), &in); err != nil {
		writeErr(ctx, fasthttp.StatusBadRequest, "invalid json")
		return
	}
	u, err := h.Store.Authenticate(in.Email, in.Password)
	if err != nil {
		writeErr(ctx, fasthttp.StatusUnauthorized, "invalid credentials")
		return
	}
	tok, err := h.Issuer.Issue(u.ID, u.Email)
	if err != nil {
		writeErr(ctx, fasthttp.StatusInternalServerError, "token error")
		return
	}
	writeJSON(ctx, fasthttp.StatusOK, loginResponse{
		AccessToken: tok.AccessToken,
		TokenType:   "bearer",
		ExpiresIn:   tok.ExpiresIn,
	})
}

func (h *Handlers) Verify(ctx *fasthttp.RequestCtx) {
	// Peek returns a view into fasthttp's header buffer — avoid the extra
	// string() copy that strings.HasPrefix would force.
	auth := ctx.Request.Header.Peek("Authorization")
	if len(auth) <= len(bearerPrefix) || !bytes.HasPrefix(auth, bearerPrefix) {
		writeErr(ctx, fasthttp.StatusUnauthorized, "missing bearer token")
		return
	}
	claims, err := h.Issuer.Decode(string(auth[len(bearerPrefix):]))
	if errors.Is(err, security.ErrExpired) {
		writeErr(ctx, fasthttp.StatusUnauthorized, "token expired")
		return
	}
	if err != nil {
		writeErr(ctx, fasthttp.StatusUnauthorized, "invalid token")
		return
	}
	if claims.Subject == "" || claims.Email == "" {
		writeErr(ctx, fasthttp.StatusUnauthorized, "malformed token")
		return
	}
	writeJSON(ctx, fasthttp.StatusOK, verifyResponse{UserID: claims.Subject, Email: claims.Email})
}
