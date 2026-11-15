from odoo import api, models


class AccountTax(models.Model):
    _inherit = "account.tax"

    @api.model
    def _sirvoy_tax_included(self, taxes):
        """Return price-included equivalents of ``taxes`` (Sirvoy amounts include VAT).

        For a tax that is not included in the price, a copy named '<name> (incl.)' with the
        same rate, group and repartition (accounts, tax report tags) is reused or created.
        """
        result = self.browse()
        for tax in taxes:
            if tax.price_include:
                result |= tax
                continue
            included = self.with_context(active_test=False).search(
                [
                    ("company_id", "=", tax.company_id.id),
                    ("type_tax_use", "=", tax.type_tax_use),
                    ("amount_type", "=", tax.amount_type),
                    ("amount", "=", tax.amount),
                    ("tax_group_id", "=", tax.tax_group_id.id),
                    ("country_id", "=", tax.country_id.id),
                    ("price_include_override", "=", "tax_included"),
                    ("children_tax_ids", "=", False),
                ],
                limit=1,
            )
            if not included:
                included = tax.copy({"name": f"{tax.name} (incl.)", "price_include_override": "tax_included"})
            result |= included
        return result
