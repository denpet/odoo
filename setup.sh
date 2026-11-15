#!/usr/bin/env bash
# Production setup / update for Odoo 19 + hotel modules (compose.prod.yaml).
# Safe to run again: first run initialises the database, later runs update addons and modules.
#
#   ./setup.sh            install / update everything and start the stack
#   ./setup.sh --no-upgrade   skip "-u all" on an existing database (faster)
set -euo pipefail

cd "$(dirname "$0")"

DB=odoo
C="docker compose -f compose.prod.yaml"
UPGRADE=1
[[ "${1:-}" == "--no-upgrade" ]] && UPGRADE=0

# Modules to install (dependencies such as account, sale, point_of_sale come automatically)
MODULES=(
  account l10n_ph om_account_accountant
  hotel hotel_reservation hotel_housekeeping hotel_restaurant
  report_hotel_reservation report_hotel_restaurant
  hotel_reservation_eden
  pos_restaurant pos_hotel_room_charge
  hotel_sirvoy_webhook
)

log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
randpw() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }

command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin is not installed"
command -v git >/dev/null || die "git is not installed"

# --- 1. Addon repositories (git-ignored, so they are not part of this repo) -------------------
clone_or_pull() {  # <dir> <url>
  if [[ -d "$1/.git" ]]; then
    log "Updating $1"
    git -C "$1" pull --ff-only
  else
    log "Cloning $2 into $1"
    git clone -b 19.0 --depth 1 "$2" "$1"
  fi
}
clone_or_pull addons/vertical-hotel https://github.com/OCA/vertical-hotel.git
clone_or_pull addons/odoomates     https://github.com/odoomates/odooapps.git

# --- 2. Secrets / config (created only if missing) -------------------------------------------
if [[ ! -f .env.prod ]]; then
  log "Creating .env.prod with a random database password"
  pw=$(randpw 32)
  umask 077
  cat > .env.prod <<EOF
DOMAIN=intranet.eden.ph
POSTGRES_PASSWORD=$pw
# must equal POSTGRES_PASSWORD (Odoo container reads this name)
PASSWORD=$pw
EOF
fi

if [[ ! -f config/odoo.prod.conf ]]; then
  log "Creating config/odoo.prod.conf (random master password, workers from CPU count)"
  workers=$(( $(nproc) * 2 + 1 ))
  umask 077
  sed -e "s/^admin_passwd = .*/admin_passwd = $(randpw 32)/" \
      -e "s/^workers = .*/workers = $workers/" \
      config/odoo.prod.conf.example > config/odoo.prod.conf
  chmod 644 config/odoo.prod.conf   # must be readable by the odoo user in the container
fi

DB_PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env.prod | cut -d= -f2-)
[[ -n "$DB_PASSWORD" && "$DB_PASSWORD" != CHANGE_ME ]] || die "Set POSTGRES_PASSWORD in .env.prod"

# --- 3. Database --------------------------------------------------------------------------------
log "Pulling images and starting PostgreSQL"
$C pull
$C up -d --wait db

psql() { $C exec -T db psql -U odoo -d "$1" -tAc "$2"; }

initialised=0
if [[ "$(psql postgres "select 1 from pg_database where datname='$DB'")" == 1 ]] \
   && [[ "$(psql "$DB" "select 1 from information_schema.tables where table_name='ir_module_module'")" == 1 ]]; then
  initialised=1
fi

odoo() { $C run --rm odoo -d "$DB" --stop-after-init "$@"; }

if (( ! initialised )); then
  log "New database: installing base"
  odoo -i base

  log "Setting company to Eden Resort / Philippines / PHP (edit scripts/setup_company_ph.py first for TIN, address)"
  $C run --rm -T --entrypoint odoo odoo shell -d "$DB" --no-http \
    --db_host=db --db_user=odoo --db_password="$DB_PASSWORD" < scripts/setup_company_ph.py
fi

# --- 4. Modules --------------------------------------------------------------------------------
# Odoo silently ignores module names it cannot find, so the result is verified below.
log "Installing modules: ${MODULES[*]}"
odoo -i "$(IFS=,; echo "${MODULES[*]}")"

if (( initialised && UPGRADE )); then
  log "Upgrading all modules (-u all)"
  odoo -u all
fi

list=$(printf "'%s'," "${MODULES[@]}"); list=${list%,}
missing=$(psql "$DB" "select name from unnest(array[$list]) as name
  where name not in (select name from ir_module_module where state='installed')")
[[ -z "$missing" ]] || die "These modules are NOT installed: $(echo $missing). Check the output above."

# --- 5. Start --------------------------------------------------------------------------------
log "Starting the stack"
$C up -d
$C restart odoo

domain=$(grep '^DOMAIN=' .env.prod | cut -d= -f2-)
log "Done. Open https://$domain:8069"
if (( ! initialised )); then
  cat <<EOF
First-time steps:
  - Log in as admin / admin and change the admin password immediately.
  - Give users Hotel Management + Sales rights (Settings -> Users).
  - Set the Sirvoy secret in System Parameter hotel_sirvoy_webhook.token.
  - Create the POS setups (Point of Sale app); each gets the "Charge to Room" method.
  - Trust Caddy's root CA on client PCs:
      $C cp caddy:/data/caddy/pki/authorities/local/root.crt eden-intranet-ca.crt
EOF
fi
