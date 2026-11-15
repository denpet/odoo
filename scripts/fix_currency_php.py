# Switch an existing database's company currency to PHP (e.g. production that ended up in USD).
# Odoo only allows this while the company has no journal items; the script checks and aborts otherwise.
#
#   C="docker compose -f compose.prod.yaml"
#   $C run --rm -T --entrypoint odoo odoo shell -d odoo --no-http --db_host=db --db_user=odoo \
#     --db_password="$(grep ^POSTGRES_PASSWORD .env.prod | cut -d= -f2)" < scripts/fix_currency_php.py
#   $C restart odoo
php = env.ref("base.PHP")
php.active = True

for c in env["res.company"].search([]):
    print(f"Company {c.name}: currency {c.currency_id.name}")
    if c.currency_id == php:
        continue
    lines = env["account.move.line"].search_count([("company_id", "=", c.id)])
    if lines:
        raise SystemExit(
            f"ABORT: {c.name} already has {lines} journal items in {c.currency_id.name}; Odoo cannot "
            "change the currency now. Those entries must be removed first (or start a fresh database)."
        )
    c.currency_id = php
    print(f"  -> currency set to PHP")

# Pricelists decide the currency of folios / sales orders; move those still in another currency.
for pl in env["product.pricelist"].with_context(active_test=False).search([("currency_id", "!=", php.id)]):
    print(f"Pricelist {pl.display_name}: {pl.currency_id.name} -> PHP")
    pl.currency_id = php

# Journals with an explicit foreign currency (normally empty = company currency).
for j in env["account.journal"].search([("currency_id", "not in", (False, php.id))]):
    print(f"Journal {j.display_name}: {j.currency_id.name} (left as is - check it is really meant to be foreign)")

env.cr.commit()
print("Done:", ", ".join(f"{c.name}={c.currency_id.name}" for c in env["res.company"].search([])))
