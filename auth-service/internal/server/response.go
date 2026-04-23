package server

import (
	"encoding/json"
	"log"

	"github.com/valyala/fasthttp"
)

// writeJSON marshals the payload up-front so fasthttp can emit a correct
// Content-Length header. Using json.NewEncoder(ctx) would stream, which is
// fine here but adds a trailing newline for no reason.
func writeJSON(ctx *fasthttp.RequestCtx, status int, body any) {
	buf, err := json.Marshal(body)
	if err != nil {
		log.Printf("encode: %v", err)
		ctx.SetStatusCode(fasthttp.StatusInternalServerError)
		return
	}
	ctx.SetStatusCode(status)
	ctx.SetContentType("application/json")
	ctx.SetBody(buf)
}

func writeErr(ctx *fasthttp.RequestCtx, status int, msg string) {
	writeJSON(ctx, status, errorBody{Error: msg})
}

type errorBody struct {
	Error string `json:"error"`
}
