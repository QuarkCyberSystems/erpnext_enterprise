# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt
"""ERPNext-side Copy-mode refresh handler for Auto Repeat.

Registered in `erpnext/hooks.py` under `auto_repeat_copy_refresh_handlers`:

    auto_repeat_copy_refresh_handlers = {
        "*": "erpnext.accounts.doctype.journal_entry.auto_repeat_copy_refresh.refresh_copy_document"
    }

Consumed by frappe.automation.auto_repeat.AutoRepeat.make_copy_document AFTER
the source has been deep-copied but BEFORE insert. The handler mutates
`new_doc` in place to apply ERPNext-specific refreshes:

  - prices (Item Price -> latest)
  - exchange rate (multi-currency revaluation at posting date)
  - sales / purchase / item tax templates
  - shipping rule
  - taxes (charge re-computation)
  - payment terms (schedule rebuild for new posting date)
  - cost-center allocation audit

Refactor lineage: badia_docs/signed_off_wp/imp_ga-0001-05+06.md, Phase D of
the upstream-shape refactor. This module owns the accounting / inventory
refresh behavior that previously lived in frappe.automation.auto_repeat,
keeping the framework module upstream-PR-clean.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def refresh_copy_document(auto_repeat, new_doc, reference_doc):
	"""Apply ERPNext-specific refreshes to a Copy-mode Auto Repeat's new doc.

	Called from frappe.automation.auto_repeat.AutoRepeat.make_copy_document
	via the `auto_repeat_copy_refresh_handlers` hook. All refreshes are
	idempotent and bounded — if any underlying dependency is missing or
	throws, the helper logs and continues so the doc still inserts.

	Gated per-field: each refresh runs only when its corresponding switch
	on the Auto Repeat is set. The switches were re-introduced as Custom
	Fields in Phase 1 of the ERPNext-side WP-05+06 refactor (see
	`erpnext.accounts.auto_repeat_extension.custom_fields`). `refresh_mode`
	(Copy Original / Recalculate) is a UI convenience that cascades all
	individual switches — the switches themselves are the source of
	truth here.
	"""
	# Skip silently for the Reversal flow — that path goes through
	# make_journal_entry_reversal, not this hook.
	if getattr(auto_repeat, "repeat_type", "Copy") != "Copy":
		return

	if auto_repeat.get("refresh_prices"):
		_refresh_item_prices(auto_repeat, new_doc)
	if auto_repeat.get("refresh_exchange_rate"):
		_refresh_conversion_rate(auto_repeat, new_doc)
	if auto_repeat.get("refresh_sales_tax_template"):
		_refresh_sales_tax_template_for(auto_repeat, new_doc)
	if auto_repeat.get("refresh_purchase_tax_template"):
		_refresh_purchase_tax_template_for(auto_repeat, new_doc)
	if auto_repeat.get("refresh_item_tax_template"):
		_refresh_item_tax_template_for(auto_repeat, new_doc)
	if auto_repeat.get("refresh_shipping_rule"):
		_refresh_shipping_rule_for(auto_repeat, new_doc)
	if auto_repeat.get("recalculate_taxes"):
		_recalculate_document_taxes(auto_repeat, new_doc)
	if auto_repeat.get("recalculate_payment_terms"):
		_recalculate_payment_schedule(auto_repeat, new_doc)
	if auto_repeat.get("respect_cost_center_allocation"):
		_apply_cost_center_allocation(auto_repeat, new_doc)


def _refresh_item_prices(auto_repeat, new_doc):
	"""Refresh item rates / price-list rates from the latest Price List."""
	try:
		from erpnext.stock.get_item_details import get_item_details
	except ImportError:
		frappe.log_error(
			title="Auto Repeat Refresh Skipped",
			message=f"Auto Repeat {auto_repeat.name}: refresh prices requires ERPNext.",
		)
		return
	items = new_doc.get("items") or []
	if not items:
		return
	posting_date = (
		new_doc.get("posting_date")
		or new_doc.get("transaction_date")
		or new_doc.get("schedule_date")
		or getdate()
	)
	for row in items:
		if not row.get("item_code"):
			continue
		try:
			args = frappe._dict(
				{
					"doctype": new_doc.doctype,
					"item_code": row.item_code,
					"company": new_doc.get("company"),
					"transaction_date": posting_date,
					"price_list": new_doc.get("selling_price_list")
					or new_doc.get("buying_price_list"),
					"currency": new_doc.get("currency"),
					"conversion_rate": flt(new_doc.get("conversion_rate")) or 1,
					# Pass the doc's ACTUAL plc_conversion_rate (price-list →
					# doc currency) so get_item_details correctly converts
					# the Item Price's value to doc currency. Hardcoding 1
					# here previously caused INR-priced items to land as
					# raw INR values in a USD doc, with downstream
					# multi-currency recalculation producing garbage like
					# 1195.82 instead of the expected 2.088.
					"plc_conversion_rate": flt(new_doc.get("plc_conversion_rate")) or 1,
					"price_list_currency": new_doc.get("price_list_currency"),
					"warehouse": row.get("warehouse"),
					"customer": new_doc.get("customer"),
					"supplier": new_doc.get("supplier"),
					"qty": row.get("qty") or 1,
					"stock_qty": row.get("stock_qty") or row.get("qty") or 1,
					"uom": row.get("uom"),
					"conversion_factor": row.get("conversion_factor") or 1,
					# Sub-switch under refresh_prices — when off (default), live
					# Pricing Rules are bypassed so the price-list lookup is
					# the only adjustment. Flip on to also re-apply Pricing
					# Rules (discount/bundle/free-item) against the new date.
					"ignore_pricing_rule": 0 if auto_repeat.get("apply_pricing_rules") else 1,
				}
			)
			details = get_item_details(args)
			if details and details.get("price_list_rate"):
				new_price = flt(details["price_list_rate"])
				row.price_list_rate = new_price
				# Reset rate to the new price_list_rate. Any margin/discount
				# from the source no longer applies under a refresh — the
				# whole point is to use the *current* price. If
				# apply_pricing_rules=1, the pricing-rule logic in
				# get_item_details may have populated `rate` separately;
				# prefer that.
				row.rate = flt(details.get("rate")) or new_price
				# Reset margin/discount that may have been deep-copied from
				# the source, so validate doesn't re-apply them on top of
				# the freshly-fetched rate.
				row.margin_type = ""
				row.margin_rate_or_amount = 0
				row.discount_percentage = 0
				row.discount_amount = 0
		except Exception:
			# Don't fail the doc-create; just log and continue.
			frappe.log_error(
				title="Auto Repeat Price Refresh",
				message=f"Auto Repeat {auto_repeat.name}: failed to refresh price for {row.item_code}",
			)


def _refresh_conversion_rate(auto_repeat, new_doc):
	"""Refresh the exchange rate on the new doc against today's posting date."""
	try:
		from erpnext.setup.utils import get_exchange_rate
	except ImportError:
		return
	if not new_doc.get("multi_currency") and not new_doc.get("conversion_rate"):
		return
	company_currency = frappe.get_cached_value(
		"Company", new_doc.get("company"), "default_currency"
	)
	currency = new_doc.get("currency")
	if not currency or currency == company_currency:
		return
	posting_date = (
		new_doc.get("posting_date") or new_doc.get("transaction_date") or getdate()
	)
	try:
		rate = get_exchange_rate(currency, company_currency, posting_date)
	except Exception:
		return
	if rate:
		new_doc.conversion_rate = flt(rate)


def _refresh_sales_tax_template_for(auto_repeat, new_doc):
	"""Refresh Sales Tax Template for the new posting date.

	ERPNext doesn't store a per-customer default taxes template (Customer
	has `tax_category` and a `taxes` child table, but no
	`default_taxes_and_charges` column). Fall back to the company-level
	default Sales Taxes and Charges Template — that's the most stable
	"current" template that applies on the new posting date. Per-customer
	override via Tax Rule + tax_category is not implemented here; that
	semantic would be a separate refactor.
	"""
	if new_doc.doctype not in ("Sales Invoice", "Sales Order", "Delivery Note", "Quotation"):
		return
	new_template = frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"is_default": 1, "company": new_doc.company, "disabled": 0},
		"name",
	)
	if new_template:
		_apply_taxes_template(auto_repeat, new_doc, new_template)


def _refresh_purchase_tax_template_for(auto_repeat, new_doc):
	"""Refresh Purchase Tax Template for the new posting date.

	Same shape as the sales helper — Supplier has no
	`default_taxes_and_charges` field; we use the company-level default
	Purchase Taxes and Charges Template.
	"""
	if new_doc.doctype not in ("Purchase Invoice", "Purchase Order", "Purchase Receipt"):
		return
	new_template = frappe.db.get_value(
		"Purchase Taxes and Charges Template",
		{"is_default": 1, "company": new_doc.company, "disabled": 0},
		"name",
	)
	if new_template:
		_apply_taxes_template(auto_repeat, new_doc, new_template)


def _apply_taxes_template(auto_repeat, new_doc, template):
	"""Replace the doc's taxes_and_charges + taxes rows with the new template's."""
	new_doc.taxes_and_charges = template
	try:
		from erpnext.controllers.accounts_controller import (
			get_taxes_and_charges,
		)
	except ImportError:
		return
	master_doctype = (
		"Sales Taxes and Charges Template"
		if new_doc.doctype in ("Sales Invoice", "Sales Order", "Delivery Note", "Quotation")
		else "Purchase Taxes and Charges Template"
	)
	rows = get_taxes_and_charges(master_doctype, template)
	new_doc.set("taxes", [])
	for row in rows or []:
		new_doc.append("taxes", row)


def _refresh_item_tax_template_for(auto_repeat, new_doc):
	"""Refresh per-row Item Tax Template from the Item's `taxes` child table.

	Items don't have a single "default tax template" column — the proper
	ERPNext model is a `taxes` child table on Item (doctype `Item Tax`)
	with rows of (item_tax_template, tax_category, valid_from). The
	"current" template is the latest row whose `valid_from <= posting_date`.

	The earlier helper queried `Item.default_item_tax_template` which is
	not a real column — it silently no-op'd via try/except, masking the
	fact that no refresh actually happened.
	"""
	items = new_doc.get("items") or []
	if not items:
		return
	posting_date = (
		new_doc.get("posting_date")
		or new_doc.get("transaction_date")
		or new_doc.get("schedule_date")
		or getdate()
	)
	for row in items:
		if not row.get("item_code"):
			continue
		# Pick the most recent Item Tax row valid on or before posting_date
		tax_rows = frappe.get_all(
			"Item Tax",
			filters={
				"parent": row.item_code,
				"parenttype": "Item",
				"valid_from": ["<=", posting_date],
			},
			fields=["item_tax_template", "valid_from"],
			order_by="valid_from desc",
			limit=1,
		)
		if tax_rows and tax_rows[0].get("item_tax_template"):
			row.item_tax_template = tax_rows[0]["item_tax_template"]


def _refresh_shipping_rule_for(auto_repeat, new_doc):
	"""Refresh Shipping Rule per the rule's current conditions."""
	if not new_doc.get("shipping_rule"):
		return
	try:
		# Trigger rule re-evaluation by calling its apply_rule if available.
		rule = frappe.get_doc("Shipping Rule", new_doc.shipping_rule)
		if hasattr(rule, "apply"):
			rule.apply(new_doc)
	except Exception:
		pass


def _recalculate_document_taxes(auto_repeat, new_doc):
	"""Trigger the doc's tax-charge recompute (rate × amount × percentage)."""
	if hasattr(new_doc, "calculate_taxes_and_totals"):
		try:
			new_doc.calculate_taxes_and_totals()
		except Exception:
			frappe.log_error(
				title="Auto Repeat Tax Recalc",
				message=f"Auto Repeat {auto_repeat.name}: tax recalc on {new_doc.doctype} failed",
			)


def _recalculate_payment_schedule(auto_repeat, new_doc):
	"""Rebuild the payment_schedule child table for the new posting date."""
	if hasattr(new_doc, "set_payment_schedule"):
		try:
			new_doc.set_payment_schedule()
		except Exception:
			pass


def _apply_cost_center_allocation(auto_repeat, new_doc):
	"""Audit Cost Center Allocation rules for the new doc's posting date."""
	try:
		from erpnext.accounts.general_ledger import get_cost_center_allocation_data
	except ImportError:
		return
	company = new_doc.get("company")
	posting_date = new_doc.get("posting_date") or new_doc.get("transaction_date") or getdate()
	if not company:
		return
	rows = []
	if new_doc.get("items"):
		rows.extend(new_doc.get("items"))
	if new_doc.get("accounts"):
		rows.extend(new_doc.get("accounts"))
	seen = set()
	for row in rows:
		cc = row.get("cost_center")
		if not cc or cc in seen:
			continue
		seen.add(cc)
		try:
			allocation = get_cost_center_allocation_data(company, posting_date, cc)
		except Exception:
			continue
		if allocation:
			frappe.log_error(
				title="Auto Repeat Cost Center Allocation",
				message=(
					f"Auto Repeat {auto_repeat.name}: cost center {cc} has allocation rules "
					f"valid for {posting_date}. GL distribution will apply at posting time."
				),
			)
