# apigate example

Три реализации одного API-шлюза поверх общей пары бэкендов —
`auth-service` и `data-service`. Публичный контракт и поведение одинаковые;
отличается только сам шлюз. Удобно сравнивать по latency / throughput /
сложности конфигурации.

- **gateway-apigate** — Rust на [apigate](https://github.com/OlegDokuchaev/apigate) 0.2.4 (эталон).
- **gateway-kong** — Kong OSS 3.7 в DB-less-режиме, логика в Lua-плагине `pre-function`.
- **gateway-python** — Granian + rloop + msgspec + aiohttp на чистом ASGI.

JWT проверяется в шлюзе через `POST /verify`; `data-service` не знает о
токенах — он видит только `x-user-id` / `x-user-email`, которые шлюз
подкладывает после проверки.

```
                ┌────────────────────┐ :8080
client ──JWT──▶ │ gateway-apigate    │ ───┐
                └────────────────────┘    │
                ┌────────────────────┐    │   ┌─────────────┐
        ──────▶ │ gateway-kong       │ ───┼──▶│ data-service│ :8002
                └────────────────────┘ :8090  │  Go fasthttp│
                ┌────────────────────┐    │   └─────────────┘
        ──────▶ │ gateway-python     │ ───┘         ▲
                └────────────────────┘ :8092        │ x-user-id
                          │                         │
                          │ POST /verify    ┌─────────────┐
                          └────────────────▶│ auth-service│ :8001
                                            │  Go fasthttp│
                                            └─────────────┘
```

## Состав

| Каталог                                          | Стек                                         | Порт         | Назначение                                  |
|--------------------------------------------------|----------------------------------------------|--------------|---------------------------------------------|
| [`auth-service/`](auth-service/README.md)        | Go, fasthttp + JWT HS256 + bcrypt            | 8001         | `/register`, `/login`, `/verify` (токен → id) |
| [`data-service/`](data-service/README.md)        | Go, fasthttp                                 | 8002         | Каталог товаров; доверяет `x-user-id`        |
| [`gateway-apigate/`](gateway-apigate/README.md)  | Rust, apigate 0.2.4                          | 8080         | Реверс-прокси с `before`-хуком, `json`, `map` |
| [`gateway-kong/`](gateway-kong/README.md)        | Kong 3.7 (DB-less) + Lua (`pre-function`)    | 8090 / 8091  | То же через декларативный конфиг Kong        |
| [`gateway-python/`](gateway-python/README.md)    | Granian + rloop + msgspec + aiohttp (ASGI)   | 8092         | То же на чистом Python ASGI                  |

Подробности по каждой реализации — в `README.md` соответствующего каталога.

## Публичный контракт

Все три шлюза отдают одинаковый набор роутов на `data-service`:

| Метод | Путь             | Поведение шлюза                                                                 |
|-------|------------------|---------------------------------------------------------------------------------|
| GET   | `/items`         | Чистое проксирование — baseline без хуков.                                       |
| GET   | `/my-items`      | Вызов `/verify`, инъекция `x-user-id`/`x-user-email`, `Authorization` снимается. |
| POST  | `/items/search`  | Валидация тела `{category?: string, max_price?: int}` → форвард как есть.        |
| POST  | `/items/lookup`  | Декод `{q: string}` → ре-кодирование в `{query, limit, source}` → форвард.       |

## Запуск через docker compose

```bash
docker compose up --build
```

Поднимается всё сразу: `auth:8001`, `data:8002`,
`gateway-apigate:8080`, `gateway-kong:8090` (admin `:8091`),
`gateway-python:8092`.

## Локальный запуск (без Docker)

```bash
# 1) auth-service  (Go)
cd auth-service && go run .

# 2) data-service  (Go)
cd data-service && go run .

# 3a) gateway-apigate  (Rust)
cd gateway-apigate && cargo run --release

# 3b) gateway-kong     (Kong OSS — только через Docker)
docker compose up --build gateway-kong

# 3c) gateway-python   (Granian)
cd gateway-python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/run.sh
```

## Пример использования

Выберите порт нужного шлюза: `8080` (apigate), `8090` (kong), `8092` (python).
Регистрация и логин — напрямую на `auth-service`; через шлюзы ходит только
каталог.

```bash
GW=http://localhost:8080        # или :8090 / :8092
AUTH=http://localhost:8001

# регистрация + логин напрямую в auth-service
curl -s -X POST $AUTH/register \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"hunter22"}'

TOKEN=$(curl -s -X POST $AUTH/login \
  -H 'content-type: application/json' \
  -d '{"email":"alice@example.com","password":"hunter22"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 1) baseline — полный каталог без авторизации
curl -s $GW/items

# 2) auth-хук — verify → x-user-id
curl -s $GW/my-items -H "Authorization: Bearer $TOKEN"

# 3) валидация тела
curl -s -X POST $GW/items/search \
  -H 'content-type: application/json' \
  -d '{"category":"office","max_price":300}'

# 4) переписывание тела (public {q} → internal schema)
curl -s -X POST $GW/items/lookup \
  -H 'content-type: application/json' \
  -d '{"q":"pen"}'

# без токена /my-items → 401
curl -i $GW/my-items
```

## Как работает авторизация

1. Клиент логинится в `auth-service` → получает JWT.
2. Защищённый роут `/my-items` вызывается с `Authorization: Bearer <jwt>`.
3. Шлюз:
   - делает `POST http://auth:8001/verify`;
   - из ответа `{user_id, email}` пишет заголовки `x-user-id` / `x-user-email`;
   - снимает `Authorization`, чтобы токен не ушёл на upstream.
4. `data-service` читает только `x-user-id`. О JWT и `auth-service` он ничего не знает.

Где живёт хук:

| Шлюз             | Файл                                                |
|------------------|-----------------------------------------------------|
| gateway-apigate  | `gateway-apigate/src/hooks.rs::require_auth`         |
| gateway-kong     | `gateway-kong/lua/require_auth.lua`                  |
| gateway-python   | `gateway-python/apigate_bench/auth_client.py` + `gateway.py::handle_my_items` |

## Конфигурация

Ключевые переменные шлюзов:

| Шлюз             | Var                                       | Назначение                                  |
|------------------|-------------------------------------------|---------------------------------------------|
| gateway-apigate  | `LISTEN_ADDR`, `AUTH_BACKEND`, `DATA_BACKEND` | URL upstream auth- и data-сервисов           |
| gateway-apigate  | `REQUEST_TIMEOUT`, `CONNECT_TIMEOUT`, `VERIFY_TIMEOUT` | `humantime`, напр. `3s` / `10s`              |
| gateway-kong     | `KONG_DECLARATIVE_CONFIG`, `KONG_PROXY_LISTEN` | читаются самим Kong; конфиг в `kong.yml`    |
| gateway-kong     | `KONG_UPSTREAM_KEEPALIVE_POOL_SIZE`, `KONG_PROXY_ACCESS_LOG`, `KONG_UNTRUSTED_LUA_SANDBOX_REQUIRES` | тюнинг пула / выключение access-лога / разрешённые модули в `pre-function` |
| gateway-python   | `ORIGIN_BASE_URL`, `AUTH_VERIFY_URL`      | точки входа upstream-ов                     |
| gateway-python   | `UPSTREAM_*_TIMEOUT`, `AUTH_*_TIMEOUT`    | секунды; auth-путь бюджетируется отдельно   |

Значения по умолчанию — в `.env` / `.env.example` каждого сервиса.

## Производительность и параллелизм

Все три шлюза настроены одинаково «по-production» — чтобы бенч сравнивал
**реализации**, а не дефолты рантаймов:

- **Auto-scaling по CPU.** tokio (apigate), nginx/Kong и granian (python)
  поднимают воркеров по числу ядер: tokio — `multi_thread` runtime с
  `available_parallelism()`, Kong — `worker_processes=auto`, granian —
  `--workers $(nproc)` через shell-CMD в `gateway-python/Dockerfile`.
- **Production-аллокатор.** apigate собирается с
  `mimalloc` как `#[global_allocator]`; python и kong — c `jemalloc` через
  `LD_PRELOAD` (см. их Dockerfile-ы). Дефолтный glibc `ptmalloc` плохо
  шкалируется на hot-path с 14+ воркерами; mimalloc/jemalloc дают 5–15% и
  стабильнее ведут себя на soak-нагрузке.
- **Kong tuning в compose.** Выключен access-log, upstream-keepalive pool
  поднят до 512, разрешён `require` модулей `require_auth` / `transforms`
  в Lua-sandbox `pre-function`.

## Нагрузочное тестирование

В [`load-tests/`](load-tests/README.md) — матрица k6-сценариев для честного
сравнения:

- **3 профиля × 4 роута = 12 прогонов на шлюз.**
- Профили: `steady` (constant-arrival-rate, 500 RPS × 2 мин),
  `ramp` (0 → 2000 RPS за 5 мин), `stress` (2500 RPS × 1 мин).
- Все — **open-model** (`constant-arrival-rate` / `ramping-arrival-rate`):
  RPS задан, latency отражает состояние шлюза, а не насыщение VU-пула.

Запуск (поднимать по одному шлюзу за раз, остальные остановить — чтобы не
делили CPU):

```bash
docker compose up -d auth data gateway-apigate

./load-tests/run.sh apigate http://localhost:8080
# -> load-tests/results/<gateway>_<route>_<profile>.json
```

Дефолты RPS перекрываются env-переменными:
`STEADY_RPS=800 STRESS_RPS=4000 ./load-tests/run.sh apigate http://localhost:8080`.
Полный список переменных (включая `COOLDOWN` между прогонами и
`*_OVERRIDE` для подмножеств матрицы) — в
[`load-tests/README.md`](load-tests/README.md).
