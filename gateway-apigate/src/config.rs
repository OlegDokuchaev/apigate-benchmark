use std::net::SocketAddr;
use std::time::Duration;

use config::{Config, ConfigError, Environment};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct AppConfig {
    pub listen_addr: SocketAddr,
    pub auth_backend: String,
    pub data_backend: String,
    #[serde(with = "humantime_serde")]
    pub request_timeout: Duration,
    #[serde(with = "humantime_serde")]
    pub connect_timeout: Duration,
    #[serde(with = "humantime_serde")]
    pub verify_timeout: Duration,
    #[serde(with = "humantime_serde")]
    pub pool_idle_timeout: Duration,
    pub data_pool_max_idle_per_host: usize,
    pub auth_pool_max_idle_per_host: usize,
    pub listen_backlog: u32,
}

impl AppConfig {
    pub fn load() -> Result<Self, ConfigError> {
        Config::builder()
            .add_source(Environment::default().try_parsing(true))
            .build()?
            .try_deserialize()
    }
}
