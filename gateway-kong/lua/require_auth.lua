-- Auth hook for /my-items.
-- Wired in kong.yml via `pre-function` → access phase.
-- Contract: verify the Bearer token against auth-service, inject
-- x-user-id / x-user-email for the upstream, strip Authorization so the
-- JWT never reaches data-service.

local http  = require "resty.http"
local cjson = require "cjson.safe"   -- .decode returns nil,err instead of throwing

local M = {}

-- verify POSTs the Authorization header to auth-service.
-- We use request_uri (not connect + request + read_body) because it reads
-- the body for us and the keepalive_* options return the socket to the
-- per-worker pool automatically. Any transport-level failure maps to
-- (nil, err); HTTP status is forwarded verbatim.
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
  local authorization = kong.request.get_header("authorization")
  if not authorization then
    return kong.response.exit(401, { error = "missing authorization header" })
  end

  local status, body = verify(authorization, config)
  if not status then
    return kong.response.exit(401, { error = "auth verify failed: " .. body })
  end
  if status >= 300 then
    -- Collapse all non-2xx (401 expired/invalid, 5xx from auth) to 401 so
    -- the gateway never leaks upstream status.
    return kong.response.exit(401, { error = "invalid or expired token" })
  end

  local parsed = cjson.decode(body)
  if not parsed or not parsed.user_id then
    return kong.response.exit(401, { error = "bad verify response" })
  end

  kong.service.request.set_header("x-user-id",    parsed.user_id)
  kong.service.request.set_header("x-user-email", parsed.email)
  kong.service.request.clear_header("Authorization")
end

return M
