-- Body validation + remap hooks for /items/search and /items/lookup.
-- Wired in kong.yml via `pre-function` → access phase.

local cjson = require "cjson.safe"

local M = {}

-- Constants for the /items/lookup remap. data-service treats `source` as an
-- opaque attribution tag; keeping it here (rather than in data-service) lets
-- every gateway label its traffic without touching the upstream.
local LOOKUP_LIMIT  = 20
local LOOKUP_SOURCE = "gateway"

-- Lua's canonical trim idiom — one pass, single capture.
local function trim(s)
  return s:match("^%s*(.-)%s*$")
end

local function is_integer(value)
  return type(value) == "number" and value == math.floor(value)
end

-- validate: /items/search body schema is { category?: string, max_price?: integer }.
-- Valid bodies are forwarded untouched; we only reject malformed input.
function M.validate()
  local body = kong.request.get_body("application/json")
  if type(body) ~= "table" then
    return kong.response.exit(400, { error = "invalid json body" })
  end
  if body.category ~= nil and type(body.category) ~= "string" then
    return kong.response.exit(400, { error = "category must be a string" })
  end
  if body.max_price ~= nil and not is_integer(body.max_price) then
    return kong.response.exit(400, { error = "max_price must be an integer" })
  end
end

-- remap: rewrite the public { q } into the internal { query, limit, source }
-- that data-service expects. set_raw_body replaces the forwarded body.
function M.remap()
  local body = kong.request.get_body("application/json")
  if type(body) ~= "table" or type(body.q) ~= "string" then
    return kong.response.exit(400, { error = "invalid json body" })
  end

  kong.service.request.set_raw_body(cjson.encode({
    query  = trim(body.q),
    limit  = LOOKUP_LIMIT,
    source = LOOKUP_SOURCE,
  }))
end

return M
