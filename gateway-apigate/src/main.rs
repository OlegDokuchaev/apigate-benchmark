mod auth_client;
mod config;
mod hooks;
mod routes;

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
    let auth_client = AuthClient::new(&cfg.auth_backend, cfg.verify_timeout)?;

    let app = apigate::App::builder()
        .mount_service(api::routes(), [cfg.data_backend])
        .state(auth_client)
        .request_timeout(cfg.request_timeout)
        .connect_timeout(cfg.connect_timeout)
        .build()?;

    println!("apigate listening on http://{}", cfg.listen_addr);
    apigate::run(cfg.listen_addr, app).await?;
    Ok(())
}
