# Run BEFORE installing accounting, on a database created with `-i base`:
#   docker compose run --rm --entrypoint odoo odoo shell -d odoo --no-http \
#     --db_host=db --db_user=odoo --db_password=<db password> < scripts/setup_company_ph.py
# Edit the values below (legal name, TIN, address) before running in production.
c = env.company
php = env.ref("base.PHP")
php.active = True
c.write({
    "name": "Eden Resort",
    "vat": False,  # TIN, e.g. "123-456-789-000"
    "street": False,
    "city": "Santander",
    "state_id": env["res.country.state"].search(
        [("country_id.code", "=", "PH"), ("name", "ilike", "Cebu")], limit=1).id,
    "country_id": env.ref("base.ph").id,
    "currency_id": php.id,
})
env.ref("base.user_admin").tz = "Asia/Manila"
env.cr.commit()
print("Company set:", c.name, c.country_id.code, c.currency_id.name)
