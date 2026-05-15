# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt
"""Custom Fields installer for the ERPNext-side Auto Repeat extension.

These fields are added to frappe's Auto Repeat doctype at install /
migrate time so the ERPNext controller override (ERPNextAutoRepeat) has
the columns it needs. The frappe doctype JSON itself is untouched.

Idempotent — safe to call repeatedly. Wired into erpnext's `after_install`
+ `after_migrate` hooks in erpnext/hooks.py.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def install_auto_repeat_custom_fields():
	"""Install the WP-05+06 Custom Fields on frappe Auto Repeat."""
	create_custom_fields(
		{
			"Auto Repeat": [
				{
					"fieldname": "repeat_type",
					"label": "Repeat Type",
					"fieldtype": "Select",
					"options": "Copy\nReversal",
					"default": "Copy",
					"reqd": 1,
					"insert_after": "reference_document",
					"description": (
						"Copy: deep-copy the source on each schedule. "
						"Reversal: route through erpnext.auto_repeat_handlers "
						"to create a reversal entry instead."
					),
				},
				{
					"fieldname": "erpnext_source_validation_section",
					"label": "Source Validation",
					"fieldtype": "Section Break",
					"insert_after": "repeat_type",
					"collapsible": 1,
				},
				{
					"fieldname": "skip_if_source_cancelled",
					"label": "Skip if Source Cancelled",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "erpnext_source_validation_section",
					"description": "Auto-disable this Auto Repeat when the source is cancelled.",
				},
				{
					"fieldname": "follow_amendment_chain",
					"label": "Follow Amendment Chain",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "skip_if_source_cancelled",
					"description": "If the source is cancelled, walk amended_from to use the latest live amendment.",
				},
				{
					"fieldname": "current_source_document",
					"label": "Current Source Document",
					"fieldtype": "Dynamic Link",
					"options": "reference_doctype",
					"read_only": 1,
					"no_copy": 1,
					"insert_after": "follow_amendment_chain",
					"description": "Updated at each fire — the doc actually used (post amendment-chain follow).",
				},
				# ── Copy Options tab (only visible when repeat_type=Copy) ─────
				{
					"fieldname": "erpnext_copy_options_tab",
					"label": "Copy Options",
					"fieldtype": "Tab Break",
					"insert_after": "current_source_document",
					"depends_on": "eval:doc.repeat_type !== 'Reversal'",
				},
				{
					"fieldname": "refresh_mode",
					"label": "Refresh Mode",
					"fieldtype": "Select",
					"options": "Copy Original\nRecalculate",
					"default": "Copy Original",
					"insert_after": "erpnext_copy_options_tab",
					"description": "Master toggle. 'Copy Original' keeps the source byte-identical (legacy). 'Recalculate' auto-enables every individual refresh switch below.",
				},
				{
					"fieldname": "refresh_prices",
					"label": "Refresh Item Prices",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_mode",
					"description": "On each copy, refresh per-item rate from the current Price List.",
				},
				{
					"fieldname": "apply_pricing_rules",
					"label": "Apply Pricing Rules",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_prices",
					"depends_on": "eval:doc.refresh_prices",
					"description": "Flip `ignore_pricing_rule` off in the price-fetch context so live Pricing Rules apply.",
				},
				{
					"fieldname": "refresh_exchange_rate",
					"label": "Refresh Exchange Rate",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "apply_pricing_rules",
					"description": "Use the current `conversion_rate` instead of the source's rate. Base amounts recalculate.",
				},
				{
					"fieldname": "recalculate_taxes",
					"label": "Recalculate Taxes",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_exchange_rate",
					"description": "Re-run `calculate_taxes_and_totals` after copy so amounts reflect current rates / items.",
				},
				{
					"fieldname": "recalculate_payment_terms",
					"label": "Recalculate Payment Schedule",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "recalculate_taxes",
					"description": "Rebuild the payment schedule from the (possibly updated) template + posting date.",
				},
				{
					"fieldname": "refresh_sales_tax_template",
					"label": "Refresh Sales Tax Template",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "recalculate_payment_terms",
					"description": "Re-fetch the Sales Taxes and Charges Template that currently matches the customer / company.",
				},
				{
					"fieldname": "refresh_purchase_tax_template",
					"label": "Refresh Purchase Tax Template",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_sales_tax_template",
					"description": "Re-fetch the Purchase Taxes and Charges Template that currently matches the supplier / company.",
				},
				{
					"fieldname": "refresh_item_tax_template",
					"label": "Refresh Item Tax Template",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_purchase_tax_template",
					"description": "Re-fetch the Item Tax Template active on the posting date (uses `valid_from`).",
				},
				{
					"fieldname": "refresh_shipping_rule",
					"label": "Refresh Shipping Rule",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_item_tax_template",
					"description": "Re-fetch the Shipping Rule currently applicable to the source.",
				},
				{
					"fieldname": "respect_cost_center_allocation",
					"label": "Respect Cost Center Allocation",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "refresh_shipping_rule",
					"description": "Audit-log only. The actual GL distribution happens in `distribute_gl_based_on_cost_center_allocation` at posting time.",
				},
			]
		},
		ignore_validate=True,
		update=True,
	)
	frappe.clear_cache(doctype="Auto Repeat")
	_install_auto_repeat_client_script()


CLIENT_SCRIPT_NAME = "ERPNext: Auto Repeat — Copy-mode refresh cascade"

_AUTO_REPEAT_CLIENT_SCRIPT = """
// WP GA-0001-05+06: when the user picks Refresh Mode = Recalculate, flip
// every individual refresh switch ON. When they flip back to Copy Original,
// reset them OFF. Wired as a Client Script (not in the doctype JS) so the
// frappe Auto Repeat module stays untouched.
frappe.ui.form.on("Auto Repeat", {
    refresh_mode: function (frm) {
        const recalc = frm.doc.refresh_mode === "Recalculate";
        const switches = [
            "refresh_prices",
            "apply_pricing_rules",
            "refresh_exchange_rate",
            "recalculate_taxes",
            "recalculate_payment_terms",
            "refresh_sales_tax_template",
            "refresh_purchase_tax_template",
            "refresh_item_tax_template",
            "refresh_shipping_rule",
            "respect_cost_center_allocation",
        ];
        switches.forEach((f) => frm.set_value(f, recalc ? 1 : 0));
    },
    repeat_type: function (frm) {
        // When user switches to Reversal mode, clear Copy-mode fields so
        // the saved state matches the visible (depends_on=hidden) UI.
        if (frm.doc.repeat_type === "Reversal") {
            frm.set_value("refresh_mode", "Copy Original");
            ["refresh_prices","apply_pricing_rules","refresh_exchange_rate",
             "recalculate_taxes","recalculate_payment_terms",
             "refresh_sales_tax_template","refresh_purchase_tax_template",
             "refresh_item_tax_template","refresh_shipping_rule",
             "respect_cost_center_allocation"].forEach((f) => frm.set_value(f, 0));
        }
    },
});
"""


def _install_auto_repeat_client_script():
	"""Install the form-level cascade Client Script. Idempotent."""
	existing = frappe.db.get_value(
		"Client Script",
		{"name": CLIENT_SCRIPT_NAME},
		["name", "script"],
		as_dict=True,
	)
	if existing and existing.get("script") == _AUTO_REPEAT_CLIENT_SCRIPT:
		return
	doc = frappe.get_doc({
		"doctype": "Client Script",
		"name": CLIENT_SCRIPT_NAME,
		"dt": "Auto Repeat",
		"view": "Form",
		"enabled": 1,
		"script": _AUTO_REPEAT_CLIENT_SCRIPT,
	})
	if existing:
		# Update existing (idempotent upsert)
		frappe.db.set_value("Client Script", CLIENT_SCRIPT_NAME, "script", _AUTO_REPEAT_CLIENT_SCRIPT)
	else:
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
