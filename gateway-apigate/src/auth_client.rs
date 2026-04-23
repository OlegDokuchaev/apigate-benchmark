use std::time::Duration;

use apigate::ApigateError;
use reqwest::Url;
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct VerifiedUser {
    pub user_id: String,
    pub email: String,
}

#[derive(Clone)]
pub struct AuthClient {
    http: reqwest::Client,
    verify_url: Url,
}

impl AuthClient {
    pub fn new(auth_backend: &str, timeout: Duration) -> anyhow::Result<Self> {
        // Build a pooled client used for every /verify on the hot path.
        // - .no_proxy() skips HTTP(S)_PROXY autodetection: the hop is internal
        //   and we never want it to leak through a caller's proxy env.
        // - tcp_keepalive keeps pooled sockets alive between k6 profile phases
        //   (steady → pause → ramp → pause → stress); without it the idle pool
        //   tears down and the next wave pays the full TCP handshake.
        // - timeout is the *total* request budget (connect + send + read).
        let http = reqwest::Client::builder()
            .timeout(timeout)
            .tcp_keepalive(Duration::from_secs(15))
            .no_proxy()
            .build()?;
        // Parse the verify URL once at startup, not once per request — reqwest's
        // IntoUrl re-parses every &str/String argument passed to .post().
        let verify_url =
            Url::parse(&format!("{}/verify", auth_backend.trim_end_matches('/')))?;
        Ok(Self { http, verify_url })
    }

    // Any failure maps to `unauthorized` so the gateway returns 401 instead of
    // leaking upstream details (connection refused, 5xx from auth, …).
    pub async fn verify(&self, authorization: &str) -> Result<VerifiedUser, ApigateError> {
        let resp = self
            .http
            .post(self.verify_url.clone())
            .header("authorization", authorization)
            .send()
            .await
            .map_err(|e| ApigateError::unauthorized(format!("auth verify failed: {e}")))?;

        if !resp.status().is_success() {
            return Err(ApigateError::unauthorized("invalid or expired token"));
        }

        resp.json::<VerifiedUser>()
            .await
            .map_err(|_| ApigateError::unauthorized("bad verify response"))
    }
}
