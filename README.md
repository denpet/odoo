# Odoo 19 + OCA Hotel Management (Docker)

Odoo 19.0 Community with the OCA [vertical-hotel](https://github.com/OCA/vertical-hotel) modules
(`hotel`, `hotel_reservation`, `hotel_housekeeping`, `hotel_restaurant`, `report_hotel_reservation`, `report_hotel_restaurant`).

```
compose.yaml              dev stack   (Odoo + Postgres, http://localhost:8069)
compose.prod.yaml         prod stack  (Odoo + Postgres + Caddy HTTPS on intranet.eden.ph)
config/odoo.dev.conf      dev Odoo config
config/odoo.prod.conf     prod Odoo config (secret, git-ignored; template: *.example)
.env.prod                 prod secrets (git-ignored; template: .env.prod.example)
caddy/                    Caddy image with GoDaddy DNS plugin + Caddyfile
addons/vertical-hotel/    git clone of OCA/vertical-hotel, branch 19.0
addons/custom/            our own modules (tracked in this repo)
```

## Addons

```bash
git clone -b 19.0 https://github.com/OCA/vertical-hotel.git addons/vertical-hotel   # first time
git -C addons/vertical-hotel pull                                                  # update
```
To add another addon repo, clone it into `addons/<repo>` and append `/mnt/extra-addons/<repo>`
to `addons_path` in both Odoo config files.

Don't edit `addons/vertical-hotel/` directly: it is git-ignored and re-cloned, so changes there are lost.
Put fixes in an override module under `addons/custom/` instead, e.g. `hotel_reservation_eden`
(fixes the reservation line dialog not opening without dates, plus a clear "add a room" error).

## Custom module: `pos_hotel_room_charge` (POS Charge to Room)

Lets the POS (restaurant with tables or plain counter) charge an order to a checked-in guest's folio.

- POS payment screen → **Charge to Room** → pick the room/guest. It must be the only payment on the order;
  refunds work the same way and add negative lines.
- Each item is added to the folio as its own line (price incl. VAT) and is invoiced at checkout.
  The folio gets a **POS Charges** button; the receipt shows the room and a guest signature line.
- Only folios that are not cancelled and where now is between check-in and check-out can be charged.

Accounting (Guest Ledger clearing account):
POS session close books revenue + VAT and debits *Guest Ledger (Room Charges)*; the folio invoice uses
the no-tax product *Restaurant / POS Room Charge* whose income account is that same clearing account, so
it moves the amount to the guest's receivable without booking revenue twice. The clearing account
should be zero for guests that have checked out and been invoiced.

On install it creates, per company: the clearing account, a *Room Charges* bank journal, the product and
the *Charge to Room* payment method, and adds the method to every POS **without an open session**.
For a POS that had a session open: close the session, then add *Charge to Room* under
Point of Sale → Configuration → Settings → Payment Methods.

Tests: `docker compose run --rm odoo -d odoo -u pos_hotel_room_charge --test-tags /pos_hotel_room_charge --stop-after-init`

## Development

```bash
docker compose up -d
```
Open http://localhost:8069 (database `odoo`, login `admin` / `admin`; DB manager master password `admin`).
Dev company: *Eden Resort* (placeholder details), Philippine chart of accounts (`l10n_ph`), PHP, 12% VAT;
POS setups *Restaurant* and *Bar*.
Python changes auto-reload; XML/QWeb are read from disk. After changing models/views run an upgrade:
```bash
docker compose run --rm odoo -d odoo -u hotel --stop-after-init
```
Reset everything: `docker compose down -v`.

## Production (intranet.eden.ph, internal network)

TLS: the host is not reachable from the internet, so Caddy gets Let's Encrypt certificates via the
**DNS-01 challenge** on GoDaddy (it creates a temporary `_acme-challenge` TXT record).

Prerequisites
1. GoDaddy production API key + secret (https://developer.godaddy.com/keys). Note: GoDaddy only grants
   DNS API access to accounts meeting its requirements (e.g. 10+ domains or Discount Domain Club) -
   check this first.
2. Internal clients must resolve `intranet.eden.ph` to the server's internal IP
   (internal DNS record, or a public A record pointing to the private IP).
3. Ports 80/443 open on the server for internal clients.

Setup
1. `.env.prod` and `config/odoo.prod.conf` have been generated with random passwords. Fill in
   `GODADDY_API_TOKEN=KEY:SECRET` in `.env.prod`. Adjust `workers` in `config/odoo.prod.conf`
   to the server (≈ CPU cores × 2 + 1).
2. Initialise the database (Philippine accounting, PHP). Edit `scripts/setup_company_ph.py` first
   (legal name, TIN, address). Demo data is off by default.
   ```bash
   C="docker compose -f compose.prod.yaml"
   $C up -d db
   $C run --rm odoo -d odoo -i base --stop-after-init
   $C run --rm --entrypoint odoo odoo shell -d odoo --no-http --db_host=db --db_user=odoo \
     --db_password="$(grep ^POSTGRES_PASSWORD .env.prod | cut -d= -f2)" < scripts/setup_company_ph.py
   $C run --rm odoo -d odoo -i account,l10n_ph --stop-after-init
   $C run --rm odoo -d odoo --stop-after-init -i \
     hotel,hotel_reservation,hotel_housekeeping,hotel_restaurant,report_hotel_reservation,report_hotel_restaurant,pos_restaurant,pos_hotel_room_charge
   ```
   Then create the POS setups from the Point of Sale app (Restaurant / Bar cards); each new POS
   automatically gets the *Charge to Room* payment method.
3. Start: `docker compose -f compose.prod.yaml up -d --build`
4. Open https://intranet.eden.ph, log in as `admin` / `admin` and **change the admin password immediately**.
5. Give users hotel access: **Settings → Users → (user) → Hotel Management: Manager or User**, plus
   **Sales** rights (folios are sales orders, so hotel staff also need a Sales group).
   The hotel modules don't assign these groups to anyone, not even `admin`; without them the app
   fails with "You are not allowed to access 'Reservation' (hotel.reservation) records".

The database manager is disabled in production (`list_db = False`).

Upgrade modules after `git pull`:
```bash
docker compose -f compose.prod.yaml run --rm odoo -d odoo -u all --stop-after-init
docker compose -f compose.prod.yaml restart odoo
```

Backups (database + filestore):
```bash
docker compose -f compose.prod.yaml exec -T db pg_dump -U odoo -Fc odoo > odoo-$(date +%F).dump
docker compose -f compose.prod.yaml run --rm --no-deps -v "$PWD":/backup --entrypoint tar odoo \
  czf /backup/filestore-$(date +%F).tgz -C /var/lib/odoo filestore
```
