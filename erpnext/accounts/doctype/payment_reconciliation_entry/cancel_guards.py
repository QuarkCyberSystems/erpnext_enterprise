# Copyright (c) 2026, QuarkCyberSystems and contributors
# License: GNU General Public License v3. See license.txt

"""Cancel-time guards for documents linked to a Payment Reconciliation Entry.

WP GA-0001-03 / GAP-004 — a Payment Entry, Journal Entry, Sales Invoice or
Purchase Invoice that has been reconciled via PRE cannot be cancelled while
the recon is still active. The reverse must happen first: the PRE must be
unreconciled (via reversal PRE) before the underlying doc can be cancelled.

Two things this module handles together:

1. `Active` means submitted (docstatus=1) AND not yet unreconciled
   (`is_unreconciled=0`). A PRE that has been reversed is still docstatus=1
   for audit but no longer represents a live reconciliation.

2. Frappe's generic link check (`check_if_doc_is_linked` in
   frappe/model/delete_doc.py) counts every submitted PRE — including
   already-unreconciled ones — and would lock the underlying doc forever.
   Each caller adds `"Payment Reconciliation Entry"` to its
   `ignore_linked_doctypes` to silence the generic check, then this module
   re-implements the check correctly (active-PREs-only).
"""

import frappe
from frappe import _


def get_active_pres(doctype: str, name: str) -> list[dict]:
	"""Return active PREs that reference the given doc on either side.

	Active = docstatus=1 AND is_unreconciled=0. PREs that have been reversed
	(is_unreconciled=1) are excluded — they no longer represent a live
	reconciliation, so they don't block cancellation of the underlying doc.
	"""
	# Payment side
	payment_side = frappe.get_all(
		"Payment Reconciliation Entry",
		filters={
			"payment_type": doctype,
			"payment_name": name,
			"docstatus": 1,
			"is_unreconciled": 0,
			"is_reversal": 0,
		},
		fields=["name", "payment_type", "payment_name", "invoice_type", "invoice_name", "allocated_amount"],
	)
	# Invoice side
	invoice_side = frappe.get_all(
		"Payment Reconciliation Entry",
		filters={
			"invoice_type": doctype,
			"invoice_name": name,
			"docstatus": 1,
			"is_unreconciled": 0,
			"is_reversal": 0,
		},
		fields=["name", "payment_type", "payment_name", "invoice_type", "invoice_name", "allocated_amount"],
	)
	# Dedupe (a PRE can in principle appear on both if doctype == invoice_type == doctype, rare)
	seen, merged = set(), []
	for row in payment_side + invoice_side:
		if row["name"] in seen:
			continue
		seen.add(row["name"])
		merged.append(row)
	return merged


def assert_no_active_pres(doctype: str, name: str) -> None:
	"""Throw with a clear, actionable message if there are any active PREs.

	Called from `before_cancel` of PE / JE / SI / PI. Lists every blocking
	PRE so the user knows exactly which ones to unreconcile.
	"""
	active = get_active_pres(doctype, name)
	if not active:
		return

	def _link(pre):
		return f'<a href="/app/payment-reconciliation-entry/{pre["name"]}">{pre["name"]}</a>'

	pre_list = "<br>".join(
		f"  • {_link(p)} ({p['payment_type']} {p['payment_name']} ↔ {p['invoice_type']} {p['invoice_name']}, "
		f"{p['allocated_amount']})"
		for p in active
	)
	frappe.throw(
		_(
			"Cannot cancel {doctype} {name} — {n} active Payment Reconciliation Entry(ies) "
			"still reference it:<br>{pre_list}<br><br>"
			"Unreconcile each one first via the linked Payment Entry / Invoice "
			"(Actions → UnReconcile)."
		).format(
			doctype=doctype,
			name=frappe.bold(name),
			n=len(active),
			pre_list=pre_list,
		),
		title=_("Active Reconciliations Exist"),
	)


def add_pre_to_ignore_linked_doctypes(doc) -> None:
	"""Extend `doc.ignore_linked_doctypes` with Payment Reconciliation Entry.

	Called from `on_cancel` of PE / JE / SI / PI. Frappe's generic link check
	runs AFTER on_cancel (see frappe/model/document.py:1379-1381), so setting
	the flag here in time. Preserves any existing tuple set by the controller.
	"""
	existing = tuple(doc.get("ignore_linked_doctypes") or ())
	if "Payment Reconciliation Entry" in existing:
		return
	doc.ignore_linked_doctypes = (*existing, "Payment Reconciliation Entry")
