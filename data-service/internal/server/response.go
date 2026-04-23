package server

import (
	"encoding/json"
	"log"

	"github.com/valyala/fasthttp"
)

// writeJSON marshals up-front so fasthttp can set Content-Length right away
// and we avoid the trailing newline json.NewEncoder would append.
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
