use serde::{Deserialize, Serialize};

use crate::hooks::require_auth;

#[derive(Debug, Deserialize)]
struct SearchInput {
    #[allow(dead_code)]
    category: Option<String>,
    #[allow(dead_code)]
    max_price: Option<i64>,
}

// Public body for /items/lookup — the gateway rewrites it into the internal
// schema before forwarding.
#[derive(Debug, Deserialize)]
struct LookupInput {
    q: String,
}

#[derive(Debug, Serialize)]
struct LookupInternal {
    query: String,
    limit: usize,
    source: &'static str,
}

#[apigate::map]
async fn remap_lookup(input: LookupInput) -> apigate::MapResult<LookupInternal> {
    Ok(LookupInternal {
        query: input.q.trim().to_string(),
        limit: 20,
        source: "gateway",
    })
}

// Four scenarios isolating the proxy / auth / validation / map overhead.
#[apigate::service]
pub mod api {
    use super::*;

    // 1) baseline — plain proxy, no hooks
    #[apigate::get("/items")]
    fn items() {}

    // 2) auth hook injects x-user-id for the upstream
    #[apigate::get("/my-items", before = [require_auth])]
    fn my_items() {}

    // 3) typed json body validation (forwarded as-is)
    #[apigate::post("/items/search", json = SearchInput)]
    fn search() {}

    // 4) typed validation + body rewrite (public `{q}` -> internal schema)
    #[apigate::post("/items/lookup", json = LookupInput, map = remap_lookup)]
    fn lookup() {}
}
