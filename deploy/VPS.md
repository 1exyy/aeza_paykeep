# Развёртывание Invoice Keeper на новом VPS

Сервер: Ubuntu 22.04 / 24.04 или Debian 12, от 1 vCPU и 2 ГБ RAM (1 ГБ — с swap), 10 ГБ диска, доступ root по SSH.

Состав в Docker Compose:

| Сервис | Что делает | Когда работает |
|---|---|---|
| `db` | PostgreSQL 16, данные в volume `pgdata` | всегда |
| `api` | FastAPI, при старте сам применяет миграции | всегда |
| `worker` | периоды, напоминания, доставка, Telegram-бот | всегда |
| `web` | собирает фронт (React) и отдаёт его nginx'ом на `/`, прокси `/api/` → `api` | всегда |
| `caddy` | HTTPS с автоматическим сертификатом Let's Encrypt | профиль `https` |
| `cloudflared` | HTTPS без домена через временный адрес `*.trycloudflare.com` | профиль `tunnel` |
| `mailpit`, `webhook-sink` | демо-ящик SMTP и демо-получатель webhook | профили `mail`, `dev` |

Telegram Mini App открывается только по **HTTPS**. Нужен домен (вариант A) или туннель (вариант B).

---

## 0. Подготовка (на своём компьютере)

1. Домен: A-запись `invoice.example.com` → IP сервера. Проверить: `nslookup invoice.example.com`.
2. Бот: у [@BotFather](https://t.me/BotFather) — `/newbot`, сохранить токен и username.
3. Групповой чат для напоминаний: создать группу и добавить в неё бота.
4. Код на сервер — клон репозитория (или архив `git archive`, скопированный через `scp`):

```bash
ssh root@SERVER_IP "apt-get update && apt-get install -y git && git clone https://github.com/1exyy/aeza_paykeep.git /opt/invoice-keeper"
```

## 1. Docker

```bash
ssh root@SERVER_IP
cd /opt/invoice-keeper
chmod +x deploy/vps/*.sh
./deploy/vps/install-docker.sh
```

Скрипт ставит Docker Engine и плагин Compose из официального apt-репозитория Docker. В ufw он открывает порты 22, 80 и 443.

## 2. Настройка

### Вариант A — свой домен (рекомендуется)

```bash
./deploy/vps/configure.sh invoice.example.com
```

### Вариант B — без домена (временный адрес)

```bash
./deploy/vps/configure.sh --tunnel
```

Скрипт создаёт `./.env` из `deploy/compose.env.example` (пароль PostgreSQL, домен) и `backend/.env` (пароль администратора, адреса, `COOKIE_SECURE=true`, `DEV_MODE=true`). Секреты генерируются прямо на сервере, **пароль администратора выводится один раз**. Существующие файлы скрипт не перезаписывает.

Затем впишите данные Telegram:

```bash
nano backend/.env
```

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_BOT_USERNAME=invoice_keeper_bot
TELEGRAM_CHAT_ID=          # см. шаг 4
```

## 3. Запуск

Вариант A (HTTPS по домену):

```bash
docker compose --profile https up -d --build
```

Вариант B (туннель):

```bash
docker compose --profile tunnel up -d --build
docker compose logs cloudflared | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
```

Полученный адрес впишите в `backend/.env` (`PUBLIC_BASE_URL=https://….trycloudflare.com`, `MINIAPP_URL=https://….trycloudflare.com/`) и перезапустите:

```bash
docker compose --profile tunnel up -d
```

Адрес туннеля меняется при каждом перезапуске `cloudflared`. Для защиты используйте вариант A.

Тестовые данные (пользователи `anna` / `anna-demo-123`, `boris` / `boris-demo-123`, четыре платежа) создаются автоматически при старте `api`, пока `SEED_DEMO_DATA=true`. Повторный запуск ничего не дублирует. Для боевого режима поставьте `SEED_DEMO_DATA=false` в `backend/.env`.

Проверка:

```bash
docker compose ps
curl -sI https://invoice.example.com/api/v1/docs | head -1
docker compose logs --tail 30 worker
```

Swagger: `https://invoice.example.com/api/v1/docs`; спецификация — `/api/v1/openapi.json` (она же `docs/api/openapi.yaml`).

## 4. Telegram

**chat_id группы.** Пока работает воркер, бот сам забирает обновления (long polling), и `getUpdates` вернёт ошибку 409. Поэтому на минуту остановите воркер:

```bash
docker compose stop worker
# напишите любое сообщение в группе с ботом, затем:
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":-[0-9]*' | sort -u
```

Впишите id (вида `-100…`) в `TELEGRAM_CHAT_ID` в `backend/.env` и примените:

```bash
docker compose up -d worker api
```

**Mini App.** В @BotFather:
- `/setmenubutton` → бот → URL `https://invoice.example.com/` → название «Invoice Keeper»;
- `/setdomain` → бот → `invoice.example.com`.

Команда `/start` в личке бота присылает кнопку открытия приложения.

**Личные напоминания** (`TELEGRAM_DM_REMINDERS=true`) приходят пользователю, только если он привязал Telegram в приложении и хотя бы раз нажал `/start` у бота.

**Проверка.** Seed-платёж «Подписка на сервис» напоминается сразу. В течение минуты после старта воркера сообщение должно прийти в группу. Статусы доставки — `GET /api/v1/notifications/deliveries` (под admin в Swagger).

**Команды и бот заявок.** Сервис обслуживает несколько команд:
- существующие данные и админ из `.env` — первая команда `DEFAULT_TEAM_NAME` (по умолчанию `aeza`); на форме входа её название вводят в поле «Команда»;
- супервайзер (`SUPERVISOR_LOGIN` / `SUPERVISOR_PASSWORD`) входит с пустым полем «Команда» и принимает или отклоняет заявки на новые команды;
- заявки принимает отдельный бот: создайте его у @BotFather и впишите токен в `APPLY_BOT_TOKEN`, затем `docker compose up -d api worker`;
- ID группы для заявки или вкладки настроек подскажет основной бот: команда `/chatid` в группе.

Пароли админа и супервайзера, изменённые в приложении, переживают перезапуск; значение из `.env` снова применяется, только если его изменить.

## 5. Фронтенд

Фронт собирается автоматически: сервис `web` выполняет `npm ci && npm run build` в Docker (Node 22) и отдаёт `dist/` через nginx. После изменений во фронте выполните:

```bash
docker compose up -d --build web
```

## 6. Демо (dev-часы)

При `DEV_MODE=true` в Swagger под admin доступны:
- `PUT /api/v1/dev/clock` `{"offset_days": 31}` — сдвинуть «сегодня»;
- `POST /api/v1/dev/run-jobs` — сразу выполнить цикл: периоды → напоминания → отправка.

После демо поставьте `DEV_MODE=false` и выполните `docker compose up -d api worker`.

## 7. Дополнительные каналы (по желанию)

Все настройки — в `backend/.env`, после правки выполните `docker compose up -d api worker`.
- **Email:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `EMAIL_RECIPIENTS`. Демо-ящик: `docker compose --profile mail up -d mailpit`, затем `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `SMTP_STARTTLS=false`; веб-интерфейс через SSH-туннель: `ssh -L 8025:127.0.0.1:8025 root@SERVER_IP` → `http://localhost:8025`.
- **Webhook:** `WEBHOOK_URL=https://…`, `WEBHOOK_SECRET=$(openssl rand -hex 32)`. Демо-получатель: `docker compose --profile dev up -d webhook-sink`, `WEBHOOK_URL=http://webhook-sink:9000/hook` (только при `DEV_MODE=true`); события видны в `docker compose logs -f webhook-sink`.
- **Slack / Mattermost / Discord:** `EXTRA_CHANNEL_URL=https://hooks.slack.com/services/…`.

## 8. Обслуживание

| Задача | Команда |
|---|---|
| Логи | `docker compose logs -f api worker` |
| Перезапуск | `docker compose restart api worker` |
| Статус | `docker compose ps` |
| Резервная копия (БД + вложения → `backups/`) | `./deploy/vps/backup.sh` |
| Обновление из нового архива | см. ниже |

Обновление (файлы `.env` и `backend/.env` не в Git и сохранятся):

```bash
cd /opt/invoice-keeper && git pull
docker compose --profile https up -d --build
```

Миграции применяются автоматически при старте `api`. Данные лежат в volume `pgdata` и `attachments` и переживают перезапуски и обновления. Не запускайте `docker compose down -v`: флаг `-v` удаляет данные.

Восстановление из копии:

```bash
docker compose exec -T db pg_restore -U postgres -d invoice_keeper --clean --if-exists < backups/<время>/db.dump
docker compose exec -T api tar -C /data -xzf - < backups/<время>/attachments.tar.gz
```

## 9. Если что-то не так

| Симптом | Что проверить |
|---|---|
| `api` перезапускается | `docker compose logs api`: пароль БД в `./.env` должен совпадать с тем, с которым создавался volume. Если меняли пароль после первого запуска, верните старый |
| Нет сертификата | `docker compose logs caddy`; A-запись домена; открыты ли 80/443 у провайдера |
| Вход не держится | `COOKIE_SECURE=true` требует HTTPS; `PUBLIC_BASE_URL` должен совпадать с адресом в браузере |
| 403 на изменениях из браузера | `PUBLIC_BASE_URL` не равен origin страницы |
| Бот теряет связь, в логе `TelegramNetworkError` / `Request timeout error` | хостер режет IPv4 до Telegram: проверьте `curl -4 -m 8 https://api.telegram.org` и `curl -6 …`; если работает только IPv6 — `TELEGRAM_IPV6_ONLY=true` в `backend/.env`, затем `docker compose up -d api worker` (IPv6 в сети compose уже включён) |
| Напоминания не приходят | `docker compose logs worker`; есть ли `TELEGRAM_BOT_TOKEN`; `GET /api/v1/notifications/deliveries` — статус и `last_error` |
| Не скачиваются образы Docker Hub | у провайдера закрыт Docker Hub: настройте зеркало в `/etc/docker/daemon.json` (`"registry-mirrors"`) и выполните `systemctl restart docker` |
