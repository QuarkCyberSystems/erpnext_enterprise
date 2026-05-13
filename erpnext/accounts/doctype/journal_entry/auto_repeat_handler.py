# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt
"""ERPNext-side handler for Auto Repeat (Reversal) on Journal Entry.

Registered in `erpnext/hooks.py` under `auto_repeat_handlers`:

    auto_repeat_handlers = {
        "Journal Entry": {
            "Reversal": "erpnext.accounts.doctype.journal_entry.auto_repeat_handler.make_journal_entry_reversal"
        }
    }

This module owns the reversal-mode behaviour that previously lived in
`frappe.automation.doctype.auto_repeat.auto_repeat.AutoRepeat.make_reversal_document`
and its helpers. Moving it here keeps `frappe/automation/auto_repeat` framework-
generic — fit for upstream — while the accounting-specific reversal semantics
(exchange-rate handling, tax-mode, cost-center-allocation, audit logging) stay
with ERPNext where they belong.

Refactor lineage: badia_docs/signed_off_wp/imp_ga-0001-05+06.md, Phase B of the
upstream-shape refactor.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, getdate


def make_journal_entry_reversal(auto_repeat, reference_doc, assignee=None):
	"""Create a reversal Journal Entry from the source via ERPNext's existing helper.

	Single-execution: the Auto Repeat is disabled after one successful insert,
	regardless of whether auto_submit_reversal succeeded.

	The `assignee` arg matches the hook contract but reversal flows don't use
	per-document assignment, so it's accepted-and-ignored.
	"""
	from erpnext.accounts.doctype.journal_entry.journal_entry import (
		make_reverse_journal_entry,
	)

	# GA-0001-01 already exposes is_reversed on the source; if the source has been
	# reversed by hand (or by a previous AR run), we never recurse — log + disable.
	if getattr(reference_doc, "is_reversed", 0):
		frappe.log_error(
			title="Auto Repeat Skipped",
			message=f"Auto Repeat {auto_repeat.name}: source {reference_doc.name} already reversed.",
		)
		auto_repeat.db_set("disabled", 1)
		auto_repeat.db_set("status", "Completed")
		if reference_doc.doctype == "Journal Entry" and reference_doc.meta.has_field(
			"auto_reversal_status"
		):
			frappe.db.set_value(
				"Journal Entry", reference_doc.name, "auto_reversal_status", "Cancelled"
			)
		return None

	reversal = make_reverse_journal_entry(reference_doc.name)

	# Reversal config (schedule + modes) is read off the source JE itself
	# rather than from the Auto Repeat. The JE inherits these fields from
	# its JE Template at insert time; storing them again on the AR was
	# the WP's original shape but kept accounting concepts in frappe.
	# Reading off the JE here lets frappe's Auto Repeat stay framework-
	# generic and upstream-shaped.
	auto_reverse_on = reference_doc.get("auto_reverse_on") or "First Day of Next Month"
	if auto_reverse_on == "First Day of Next Month":
		reversal.posting_date = get_first_day(add_months(getdate(), 1))
	elif auto_reverse_on == "Specific Date" and reference_doc.get("auto_reverse_date"):
		reversal.posting_date = getdate(reference_doc.auto_reverse_date)

	# WP GAP-013/014 — make_reverse_journal_entry does not copy cost_center / party / project.
	_enhance_reversal_mapping(reversal, reference_doc)

	# WP GAP-021 / Phase 5.1 — FX handling
	if reference_doc.get("reversal_exchange_rate_type") == "Current Rate":
		_refresh_reversal_exchange_rate(reversal)

	# WP GAP-022 — cost-center allocation audit
	if reference_doc.get("reversal_cost_center_mode") == "Apply Current Allocation":
		_apply_reversal_cost_center_allocation(auto_repeat, reversal)

	# WP GAP-021 — tax recalculation (audit-only — see imp plan §6 sign-off #4)
	if reference_doc.get("reversal_tax_mode") == "Recalculate for Posting Date":
		_recalculate_reversal_taxes(auto_repeat, reversal)

	reversal.user_remark = (reversal.user_remark or "") + (
		f"\nAuto-created by Auto Repeat {auto_repeat.name}".strip()
	)
	reversal.flags.ignore_permissions = True
	reversal.flags.updater_reference = {
		"doctype": auto_repeat.doctype,
		"docname": auto_repeat.name,
		"label": _("via Auto Repeat (Reversal)"),
	}
	reversal.insert()

	# Wire the JE-side status fields
	je_meta = frappe.get_meta("Journal Entry")
	updates = {}
	if je_meta.has_field("linked_auto_repeat"):
		updates["linked_auto_repeat"] = auto_repeat.name
	if je_meta.has_field("auto_reversal_status"):
		updates["auto_reversal_status"] = "Scheduled"
	if updates:
		frappe.db.set_value("Journal Entry", reference_doc.name, updates)

	if reference_doc.get("auto_submit_reversal"):
		try:
			reversal.submit()
			if je_meta.has_field("auto_reversal_status"):
				frappe.db.set_value(
					"Journal Entry", reference_doc.name, "auto_reversal_status", "Completed"
				)
		except Exception:
			if je_meta.has_field("auto_reversal_status"):
				frappe.db.set_value(
					"Journal Entry", reference_doc.name, "auto_reversal_status", "Failed"
				)
			raise

	# Single-execution semantics — disable after first successful insert
	auto_repeat.db_set("disabled", 1)
	auto_repeat.db_set("status", "Completed")
	return reversal


def _enhance_reversal_mapping(reversal, original):
	"""Copy cost_center / party / project / user_remark per-row.

	make_reverse_journal_entry's field_map only swaps debit <-> credit; everything
	else needs explicit copying. We pair rows positionally because the field_map
	preserves row order.
	"""
	for i, row in enumerate(reversal.accounts):
		if i >= len(original.accounts):
			break
		orig = original.accounts[i]
		row.cost_center = orig.get("cost_center")
		row.project = orig.get("project")
		row.party_type = orig.get("party_type")
		row.party = orig.get("party")
		if not row.user_remark and orig.get("user_remark"):
			row.user_remark = orig.user_remark


def _refresh_reversal_exchange_rate(reversal):
	"""Revalue the reversal at the FX rate of the reversal posting date.

	Breaks immutable-ledger compliance — the operator was warned at save time.
	"""
	try:
		from erpnext.setup.utils import get_exchange_rate
	except ImportError:
		return
	if not getattr(reversal, "multi_currency", 0):
		return
	posting_date = reversal.posting_date or getdate()
	company_currency = frappe.get_cached_value(
		"Company", reversal.company, "default_currency"
	)
	for row in reversal.accounts:
		if row.account_currency and row.account_currency != company_currency:
			try:
				new_rate = get_exchange_rate(
					row.account_currency, company_currency, posting_date
				)
			except Exception:
				continue
			if new_rate:
				row.exchange_rate = flt(new_rate)
				row.debit = flt(row.debit_in_account_currency) * flt(new_rate)
				row.credit = flt(row.credit_in_account_currency) * flt(new_rate)
	if hasattr(reversal, "set_total_debit_credit"):
		reversal.set_total_debit_credit()


def _apply_reversal_cost_center_allocation(auto_repeat, reversal):
	"""Audit Cost Center Allocation rules for the reversal posting date."""
	try:
		from erpnext.accounts.general_ledger import get_cost_center_allocation_data
	except ImportError:
		return
	posting_date = reversal.posting_date or getdate()
	company = reversal.company
	seen = set()
	for row in reversal.accounts:
		if not row.cost_center or row.cost_center in seen:
			continue
		seen.add(row.cost_center)
		try:
			allocation = get_cost_center_allocation_data(
				company, posting_date, row.cost_center
			)
		except Exception:
			continue
		if allocation:
			frappe.log_error(
				title="Auto Repeat Reversal Cost Center Allocation",
				message=(
					f"Auto Repeat {auto_repeat.name}: cost center {row.cost_center} "
					f"has allocation rules valid for {posting_date}. "
					f"GL distribution will apply at posting time."
				),
			)


def _recalculate_reversal_taxes(auto_repeat, reversal):
	"""Audit-only tax recalculation check for the reversal posting date.

	True recalculation needs ERPNext's tax-template engine, which depends on
	context (Sales/Purchase tax templates aren't usually on JE rows). We
	log a notice that an audit-trail entry might be needed.
	"""
	# Audit log only — explicit recalc on JE rows requires a tax-template path
	# that isn't exposed by JE. Operators reach this only by deliberately
	# selecting "Recalculate for Posting Date" + acknowledging the warning.
	frappe.log_error(
		title="Auto Repeat Reversal Tax Mode = Recalculate",
		message=(
			f"Auto Repeat {auto_repeat.name}: reversal_tax_mode=Recalculate is "
			f"audit-only for Journal Entry. Reversal {reversal.name} retains the "
			f"original tax amounts. Manually adjust tax rows if a different posting-"
			f"date tax treatment is required."
		),
	)
