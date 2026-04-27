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
    pub fn new(
        auth_backend: &str,
        timeout: Duration,
        pool_idle_timeout: Duration,
    ) -> anyhow::Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(timeout)
            .tcp_keepalive(Duration::from_secs(15))
            .tcp_nodelay(true)
            .http1_only()
            .pool_idle_timeout(pool_idle_timeout)
            .pool_max_idle_per_host(256)
            .no_proxy()
            .build()?;
        let verify_url = Url::parse(&format!("{}/verify", auth_backend.trim_end_matches('/')))?;
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
