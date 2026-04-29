-- Auth hook for /my-items.
-- Wired in apisix.yaml via `serverless-pre-function` -> access phase.
-- Contract: verify the Bearer token against auth-service, inject
-- x-user-id / x-user-email for the upstream, strip Authorization so the
-- JWT never reaches data-service.

local http  = require "resty.http"
local cjson = require "cjson.safe"   -- .decode returns nil,err instead of throwing

local M = {}

local function exit_json(status, message)
  ngx.status = status
  ngx.header["Content-Type"] = "application/json"
  ngx.say(cjson.encode({ error = message }))
  return ngx.exit(status)
end

-- verify POSTs the Authorization header to auth-service.
-- request_uri reads the body and returns the socket to the per-worker
-- keepalive pool automatically when keepalive_* options are set.
local function verify(authorization, config)
  local httpc = http.new()
  httpc:set_timeout(config.verify_timeout_ms)

  local res, err = httpc:request_uri(config.auth_url, {
    method  = "POST",
    headers = { Authorization = authorization },
    keepalive_timeout = config.keepalive_timeout_ms,
    keepalive_pool    = config.keepalive_pool,
  })
  if not res then
    return nil, tostring(err)
  end
  return res.status, res.body
end

function M.run(config)
  local headers = ngx.req.get_headers()
  local authorization = headers.authorization or headers.Authorization
  if not authorization then
    return exit_json(401, "missing authorization header")
  end

  local status, body = verify(authorization, config)
  if not status then
    return exit_json(401, "auth verify failed: " .. body)
  end
  if status >= 300 then
    -- Collapse all non-2xx (401 expired/invalid, 5xx from auth) to 401 so
    -- the gateway never leaks upstream status.
    return exit_json(401, "invalid or expired token")
  end

  local parsed = cjson.decode(body)
  if not parsed or not parsed.user_id then
    return exit_json(401, "bad verify response")
  end

  ngx.req.set_header("x-user-id", tostring(parsed.user_id))
  ngx.req.set_header("x-user-email", parsed.email)
  ngx.req.clear_header("Authorization")
end

return M
