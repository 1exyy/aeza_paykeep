#!/usr/bin/env bash
# First-time configuration on the server: creates ./.env and backend/.env from the templates
# with freshly generated secrets. Never overwrites existing files.
#
#   ./deploy/vps/configure.sh invoice.example.com     # HTTPS by domain (Caddy)
#   ./deploy/vps/configure.sh --tunnel                # no domain: temporary Cloudflare URL
set -euo pipefail
cd "$(dirname "$0")/../.."

MODE=https
DOMAIN="${1:-}"
if [[ "$DOMAIN" == "--tunnel" ]]; then MODE=tunnel; DOMAIN=""; fi
if [[ "$MODE" == https && -z "$DOMAIN" ]]; then
  echo "Usage: $0 <domain> | --tunnel"; exit 1
fi

for f in .env backend/.env; do
  if [[ -e "$f" ]]; then echo "$f already exists — not touching it."; exit 1; fi
done

set_kv() {  # set_kv FILE KEY VALUE
  local file="$1" key="$2" value="$3"
  if grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

PG_PASSWORD="$(openssl rand -hex 24)"
ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
SUPERVISOR_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
TOTP_ENCRYPTION_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"

cp deploy/compose.env.example .env
set_kv .env POSTGRES_PASSWORD "$PG_PASSWORD"
set_kv .env DOMAIN "$DOMAIN"
if [[ "$MODE" == https ]]; then set_kv .env WEB_PORT "127.0.0.1:8080"; else set_kv .env WEB_PORT "8080"; fi

cp backend/.env.example backend/.env
set_kv backend/.env ADMIN_LOGIN admin
set_kv backend/.env ADMIN_PASSWORD "$ADMIN_PASSWORD"
set_kv backend/.env TOTP_ENCRYPTION_KEY "$TOTP_ENCRYPTION_KEY"
set_kv backend/.env DEFAULT_TEAM_NAME aeza
set_kv backend/.env SUPERVISOR_LOGIN supervisor
set_kv backend/.env SUPERVISOR_PASSWORD "$SUPERVISOR_PASSWORD"
set_kv backend/.env COOKIE_SECURE true
set_kv backend/.env DEV_MODE true
set_kv backend/.env SEED_DEMO_DATA true
set_kv backend/.env ATTACHMENTS_DIR /data/attachments
if [[ "$MODE" == https ]]; then
  set_kv backend/.env PUBLIC_BASE_URL "https://$DOMAIN"
  set_kv backend/.env MINIAPP_URL "https://$DOMAIN/"
fi
chmod 600 .env backend/.env

cat <<MSG
Created .env and backend/.env (mode $MODE).

  Team:                   aeza   (typed on the login form)
  Administrator login:    admin
  Administrator password: $ADMIN_PASSWORD
  Supervisor login:       supervisor   (empty team on the login form)
  Supervisor password:    $SUPERVISOR_PASSWORD
  (shown once; both are also in backend/.env)

Still to fill in backend/.env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_BOT_USERNAME,
APPLY_BOT_TOKEN for team applications (and SMTP_*/WEBHOOK_*/EXTRA_CHANNEL_URL if needed). DEV_MODE=true enables the demo clock;
set it to false outside the demo.
MSG
if [[ "$MODE" == tunnel ]]; then
  echo "Tunnel mode: after start, put the https://….trycloudflare.com URL into PUBLIC_BASE_URL and MINIAPP_URL."
fi
