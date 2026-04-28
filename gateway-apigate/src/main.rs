mod auth_client;
mod config;
mod hooks;
mod routes;

use std::time::Duration;

use crate::auth_client::AuthClient;
use crate::config::AppConfig;
use crate::routes::api;

// mimalloc scales much better than glibc ptmalloc for the short-lived
// allocations on the request hot path (header maps, body buffers, serde).
#[global_allocator]
static GLOBAL: mimalloc::MiMalloc = mimalloc::MiMalloc;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cfg = AppConfig::load()?;
    let auth_client = AuthClient::new(
        &cfg.auth_backend,
        cfg.verify_timeout,
        cfg.pool_idle_timeout,
        cfg.auth_pool_max_idle_per_host,
    )?;

    let upstream = apigate::UpstreamConfig::default()
        .connect_timeout(cfg.connect_timeout)
        .pool_idle_timeout(cfg.pool_idle_timeout)
        .pool_max_idle_per_host(cfg.data_pool_max_idle_per_host)
        .configure_connector(|connector| {
            connector.set_keepalive(Some(Duration::from_secs(30)));
        });

    let app = apigate::App::builder()
        .mount_service(api::routes(), [cfg.data_backend])
        .state(auth_client)
        .request_timeout(cfg.request_timeout)
        .upstream(upstream)
        .build()?;

    let serve_cfg = apigate::ServeConfig::new()
        .backlog(cfg.listen_backlog)
        .tcp_nodelay(true);

    println!(
        "apigate listening on http://{} (backlog={})",
        cfg.listen_addr, cfg.listen_backlog,
    );
    apigate::run_with(cfg.listen_addr, app, serve_cfg).await?;
    Ok(())
}
