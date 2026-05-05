# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt
"""WP GA-0001-03 Payment Reconciliation Entry — migration cut-over notice.

This patch is informational only — it writes no data. It logs a
one-time message explaining that historical reconciliations recorded
before this migration are NOT back-populated as Payment Reconciliation
Entry rows.

Pre-migration reconciliations remain auditable via the legacy
Payment Entry Reference rows + clearing GL entries posted under
voucher_type='Payment Entry'. Post-migration reconciliations under
Immutable Ledger flow through the new PRE doctype with clearing GL
under voucher_type='Payment Reconciliation Entry'.

The two coexist on the same Payment Entry without conflict: PE
Reference rows whose `reconciliation_entry` field is NULL are
pre-migration; rows with `reconciliation_entry` set are PRE-driven.
"""

import frappe


def execute():
	frappe.msgprint(
		"Payment Reconciliation Entry (PRE) coverage starts at this migration "
		"cut-over date. Historical reconciliations are NOT back-populated as "
		"PRE rows. Pre-migration reconciliations remain auditable via the "
		"legacy Payment Entry Reference + clearing GL (voucher_type='Payment "
		"Entry') pattern. See WP GA-0001-03 §A8.",
		alert=False,
	)
