-- Body validation + remap hooks for /items/search and /items/lookup.
-- Wired in apisix.yaml via `serverless-pre-function` -> access phase.

local cjson = require "cjson.safe"

local M = {}

-- Constants for the /items/lookup remap. data-service treats `source` as an
-- opaque attribution tag; keeping it here (rather than in data-service) lets
-- every gateway label its traffic without touching the upstream.
local LOOKUP_LIMIT  = 20
local LOOKUP_SOURCE = "gateway"

local function exit_json(status, message)
  ngx.status = status
  ngx.header["Content-Type"] = "application/json"
  ngx.say(cjson.encode({ error = message }))
  return ngx.exit(status)
end

-- Lua's canonical trim idiom -- one pass, single capture.
local function trim(s)
  return s:match("^%s*(.-)%s*$")
end

local function is_integer(value)
  return type(value) == "number" and value == math.floor(value)
end

local function read_json_body()
  ngx.req.read_body()
  local raw = ngx.req.get_body_data()
  if not raw then
    return nil
  end
  local body = cjson.decode(raw)
  return body
end

-- validate: /items/search body schema is { category?: string, max_price?: integer }.
-- Valid bodies are forwarded untouched; we only reject malformed input.
function M.validate()
  local body = read_json_body()
  if type(body) ~= "table" then
    return exit_json(400, "invalid json body")
  end
  if body.category ~= nil and type(body.category) ~= "string" then
    return exit_json(400, "category must be a string")
  end
  if body.max_price ~= nil and not is_integer(body.max_price) then
    return exit_json(400, "max_price must be an integer")
  end
end

-- remap: rewrite the public { q } into the internal { query, limit, source }
-- that data-service expects. set_body_data replaces the forwarded body.
function M.remap()
  local body = read_json_body()
  if type(body) ~= "table" or type(body.q) ~= "string" then
    return exit_json(400, "invalid json body")
  end

  local new_body = cjson.encode({
    query  = trim(body.q),
    limit  = LOOKUP_LIMIT,
    source = LOOKUP_SOURCE,
  })

  ngx.req.set_body_data(new_body)
  ngx.req.set_header("Content-Type", "application/json")
  ngx.req.set_header("Content-Length", #new_body)
end

return M
