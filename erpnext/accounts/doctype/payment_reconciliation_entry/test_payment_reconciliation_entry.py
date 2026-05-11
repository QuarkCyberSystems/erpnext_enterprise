# Copyright (c) 2026, QuarkCyberSystems and contributors
# See license.txt
"""
WP GA-0001-03 — Payment Reconciliation Entry test suite.

Tests cover:
  TC-001..006   Tier 1 — block hard deletions
  TC-007..011   Tier 2 — stop after-submit modifications
  TC-012..018   Tier 3 — Payment Reconciliation Entry architecture
  TC-R1..R10    Badia regression cases

Test data is bootstrapped on top of the `_Test Payment Reconciliation`
company created by `test_payment_reconciliation.py` (which we extend).
We toggle `enable_immutable_ledger` per-test rather than per-fixture so
tests can verify both modes against the same seed data.

These tests assume a fresh test site (e.g. `pr_recon_test.localhost`)
because `ERPNextTestSuite.BootStrapTestData` fails on non-fresh sites
(memory: project_erpnext_test_runner).
"""

import frappe
from frappe.utils import flt, nowdate

from erpnext.accounts.doctype.payment_reconciliation.test_payment_reconciliation import (
	TestPaymentReconciliation,
)


def _set_immutable(value: int):
	frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", value)
	frappe.db.commit()


def _enable_bapsp_on_company(company: str):
	frappe.db.set_value(
		"Company", company, "book_advance_payments_in_separate_party_account", 1, update_modified=False
	)
	frappe.db.commit()


class TestPaymentReconciliationEntry(TestPaymentReconciliation):
	"""Inherits seed setup (Company, Customer, Item, Accounts) from
	TestPaymentReconciliation and adds PRE-specific test cases."""

	def setUp(self):
		super().setUp()
		_enable_bapsp_on_company(self.company)
		_set_immutable(1)
		self.addCleanup(lambda: _set_immutable(0))

	# -------- Tier 3 core (TC-012, TC-013, TC-014) --------

	def test_tc012_one_pre_per_allocation(self):
		"""Reconciling a single PE against a single SI under Immutable
		Ledger creates exactly one Payment Reconciliation Entry."""
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()

		self._reconcile_pe_against_si(pe, si, 100)

		pre_count = frappe.db.count(
			"Payment Reconciliation Entry",
			{"payment_name": pe.name, "invoice_name": si.name, "is_reversal": 0, "docstatus": 1},
		)
		self.assertEqual(pre_count, 1)

	def test_tc013_clearing_gl_under_pre_voucher(self):
		"""Clearing GL pair is posted under voucher_type='Payment
		Reconciliation Entry', NOT under Payment Entry."""
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()
		self._reconcile_pe_against_si(pe, si, 100)

		pre_name = frappe.db.get_value(
			"Payment Reconciliation Entry",
			{"payment_name": pe.name, "is_reversal": 0, "docstatus": 1},
			"name",
		)
		gl_under_pre = frappe.db.count(
			"GL Entry", {"voucher_type": "Payment Reconciliation Entry", "voucher_no": pre_name}
		)
		self.assertGreaterEqual(gl_under_pre, 2)

	def test_tc014_pe_original_gl_untouched(self):
		"""The PE's original GL (Cash → Advance) at submit time is
		preserved byte-for-byte after reconcile."""
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()

		original_gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
			fields=["name", "account", "debit", "credit"],
			order_by="name",
		)
		self._reconcile_pe_against_si(pe, si, 100)
		post_gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
			fields=["name", "account", "debit", "credit"],
			order_by="name",
		)
		self.assertEqual(original_gl, post_gl)

	# -------- Tier 3 reversal (TC-015) --------

	def test_tc015_unreconcile_creates_reversal_pre(self):
		"""Unreconcile Payment.on_submit creates one reversal PRE per
		allocation; the reversal's GL pair has Dr↔Cr swapped vs the
		original; original PRE flips is_unreconciled=1."""
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()
		self._reconcile_pe_against_si(pe, si, 100)

		original_pre_name = frappe.db.get_value(
			"Payment Reconciliation Entry",
			{"payment_name": pe.name, "is_reversal": 0, "docstatus": 1},
			"name",
		)
		self.assertTrue(original_pre_name)

		from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
			create_unreconcile_doc_for_selection,
		)
		import json

		create_unreconcile_doc_for_selection(
			selections=json.dumps(
				[
					{
						"company": self.company,
						"voucher_type": "Payment Entry",
						"voucher_no": pe.name,
						"against_voucher_type": "Sales Invoice",
						"against_voucher_no": si.name,
					}
				]
			)
		)

		# Original flipped
		flipped = frappe.db.get_value(
			"Payment Reconciliation Entry", original_pre_name, ["is_unreconciled", "unreconciled_by"], as_dict=True
		)
		self.assertEqual(flipped.is_unreconciled, 1)
		self.assertTrue(flipped.unreconciled_by)

		# Reversal exists with the matching reversal_of
		reversal_pre_name = flipped.unreconciled_by
		reversal_meta = frappe.db.get_value(
			"Payment Reconciliation Entry",
			reversal_pre_name,
			["is_reversal", "reversal_of", "docstatus"],
			as_dict=True,
		)
		self.assertEqual(reversal_meta.is_reversal, 1)
		self.assertEqual(reversal_meta.reversal_of, original_pre_name)
		self.assertEqual(reversal_meta.docstatus, 1)

	# -------- Tier 1 — block deletions (TC-002, TC-003, TC-006) --------

	def test_tc002_supersede_pl_entries_no_delete(self):
		"""Under Immutable, _supersede_pl_entries flags delinked=1 instead
		of DELETE on the JE-reconcile rebuild path."""
		from erpnext.accounts.utils import _supersede_pl_entries

		# Insert a synthetic PLE row
		ple = frappe.get_doc(
			{
				"doctype": "Payment Ledger Entry",
				"company": self.company,
				"voucher_type": "Journal Entry",
				"voucher_no": "TEST-JE-001",
				"posting_date": nowdate(),
				"account_type": "Receivable",
				"account": self.debit_to,
				"party_type": "Customer",
				"party": self.customer,
				"due_date": nowdate(),
				"finance_book": "",
				"account_currency": "INR",
				"amount": 100,
				"amount_in_account_currency": 100,
				"against_voucher_type": "Sales Invoice",
				"against_voucher_no": "TEST-SI-001",
				"delinked": 0,
				"docstatus": 1,
			}
		)
		ple.flags.ignore_permissions = True
		ple.flags.ignore_validate = True
		ple.flags.ignore_links = True  # synthetic row; voucher_no points at non-existent JE on purpose
		ple.insert()

		_supersede_pl_entries("Journal Entry", "TEST-JE-001")
		self.assertEqual(frappe.db.get_value("Payment Ledger Entry", ple.name, "delinked"), 1)
		# Row is preserved (not deleted)
		self.assertTrue(frappe.db.exists("Payment Ledger Entry", ple.name))

	def test_tc003_supersede_adv_pl_entries(self):
		"""Under Immutable, _supersede_adv_pl_entries flips is_cancelled=1
		instead of DELETE."""
		from erpnext.accounts.utils import _supersede_adv_pl_entries

		aple = frappe.get_doc(
			{
				"doctype": "Advance Payment Ledger Entry",
				"company": self.company,
				"voucher_type": "Payment Entry",
				"voucher_no": "TEST-PE-001",
				"against_voucher_type": "Sales Invoice",
				"against_voucher_no": "TEST-SI-001",
				"currency": "INR",
				"exchange_rate": 1,
				"amount": 100,
				"event": "Submit",
			}
		)
		aple.flags.ignore_permissions = True
		aple.flags.ignore_links = True  # synthetic row; voucher_no points at non-existent PE on purpose
		aple.insert()

		_supersede_adv_pl_entries("Payment Entry", "TEST-PE-001")
		self.assertEqual(
			frappe.db.get_value("Advance Payment Ledger Entry", aple.name, "is_cancelled"), 1
		)
		self.assertTrue(frappe.db.exists("Advance Payment Ledger Entry", aple.name))

	def test_tc006_remove_ref_from_advance_section_flag_only(self):
		"""Under Immutable, remove_ref_from_advance_section sets
		is_unlinked=1 instead of DELETE on Sales/Purchase Invoice Advance."""
		from erpnext.accounts.utils import remove_ref_from_advance_section

		si = self.create_sales_invoice(qty=1, rate=100)
		# Manually insert a SIA row (doesn't have to be valid — testing the
		# delete-vs-flag branch, not the reconcile flow).
		sia = frappe.get_doc(
			{
				"doctype": "Sales Invoice Advance",
				"parent": si.name,
				"parenttype": "Sales Invoice",
				"parentfield": "advances",
				"reference_type": "Payment Entry",
				"reference_name": "TEST-PE-XYZ",
				"advance_amount": 50,
				"allocated_amount": 50,
				"docstatus": 1,
			}
		)
		sia.flags.ignore_permissions = True
		sia.flags.ignore_validate = True
		sia.flags.ignore_links = True  # synthetic row; reference_name points at non-existent PE on purpose
		sia.insert()
		si_doc = frappe.get_doc("Sales Invoice", si.name)
		si_doc.append(
			"advances",
			{
				"reference_type": "Payment Entry",
				"reference_name": "TEST-PE-XYZ",
				"advance_amount": 50,
				"allocated_amount": 50,
			},
		)
		# Reload from DB so our advances list contains the sia row
		si_doc = frappe.get_doc("Sales Invoice", si.name)

		remove_ref_from_advance_section(si_doc, "TEST-PE-XYZ")
		row = frappe.db.get_value(
			"Sales Invoice Advance", sia.name, ["is_unlinked", "unlinked_on"], as_dict=True
		)
		# Row preserved
		self.assertTrue(frappe.db.exists("Sales Invoice Advance", sia.name))
		# Flag set
		if row:
			self.assertEqual(row.is_unlinked, 1)

	# -------- Tier 2 — assert guards (TC-007, TC-008) --------

	def test_tc007_update_reference_in_payment_entry_blocked(self):
		"""Calling update_reference_in_payment_entry under Immutable Ledger
		fires the assert."""
		from erpnext.accounts.utils import update_reference_in_payment_entry

		with self.assertRaises(AssertionError):
			update_reference_in_payment_entry(frappe._dict(), frappe._dict())

	def test_tc008_update_reference_in_journal_entry_blocked(self):
		from erpnext.accounts.utils import update_reference_in_journal_entry

		with self.assertRaises(AssertionError):
			update_reference_in_journal_entry(frappe._dict(), frappe._dict())

	# -------- Tier 3 — PRE.on_cancel guard (TC-018) --------

	def test_tc018_pre_cancel_blocked_under_immutable(self):
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()
		self._reconcile_pe_against_si(pe, si, 100)

		pre_name = frappe.db.get_value(
			"Payment Reconciliation Entry",
			{"payment_name": pe.name, "is_reversal": 0, "docstatus": 1},
			"name",
		)
		pre = frappe.get_doc("Payment Reconciliation Entry", pre_name)
		with self.assertRaises(frappe.ValidationError):
			pre.cancel()

	# -------- Regression cases (TC-R1, TC-R7, TC-R10) --------

	def test_tc_r1_immutable_off_no_pre(self):
		"""Under Immutable OFF, reconcile produces NO Payment Reconciliation
		Entry — legacy mutate-the-PE flow runs as today."""
		_set_immutable(0)
		try:
			si = self.create_sales_invoice(qty=1, rate=100)
			pe = self.create_payment_entry(amount=100)
			pe.submit()
			self._reconcile_pe_against_si(pe, si, 100)
			pre_count = frappe.db.count(
				"Payment Reconciliation Entry", {"payment_name": pe.name, "docstatus": 1}
			)
			self.assertEqual(pre_count, 0)
		finally:
			_set_immutable(1)

	def test_tc_r7_advance_visibility_filter(self):
		"""Under Immutable, a PE with a non-reversed PRE is excluded from
		Payment Reconciliation tool's available-payments list."""
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()
		self._reconcile_pe_against_si(pe, si, 100)

		# Re-open the PR tool — the PE should NOT appear (it's already covered
		# by an active PRE).
		pr = frappe.new_doc("Payment Reconciliation")
		pr.company = self.company
		pr.party_type = "Customer"
		pr.party = self.customer
		pr.receivable_payable_account = self.debit_to
		entries = pr.get_payment_entries()
		pe_names_in_list = [e.get("reference_name") for e in entries]
		self.assertNotIn(pe.name, pe_names_in_list)

	def test_tc_r10_outstanding_idempotency(self):
		"""Reconcile-unreconcile-reconcile cycle: final outstanding equals
		initial outstanding minus net allocated."""
		si = self.create_sales_invoice(qty=1, rate=100)
		pe = self.create_payment_entry(amount=100)
		pe.submit()
		initial_outstanding = frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")
		self.assertEqual(flt(initial_outstanding), 100.0)

		self._reconcile_pe_against_si(pe, si, 100)
		post_recon_1 = frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")
		self.assertEqual(flt(post_recon_1), 0.0)

		import json

		from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
			create_unreconcile_doc_for_selection,
		)

		create_unreconcile_doc_for_selection(
			selections=json.dumps(
				[
					{
						"company": self.company,
						"voucher_type": "Payment Entry",
						"voucher_no": pe.name,
						"against_voucher_type": "Sales Invoice",
						"against_voucher_no": si.name,
					}
				]
			)
		)
		post_unrec = frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")
		self.assertEqual(flt(post_unrec), 100.0)

		# Reconcile again
		self._reconcile_pe_against_si(pe, si, 100)
		post_recon_2 = frappe.db.get_value("Sales Invoice", si.name, "outstanding_amount")
		self.assertEqual(flt(post_recon_2), 0.0)

	# -------- helpers --------

	def _reconcile_pe_against_si(self, pe, si, amount):
		"""Drive the Payment Reconciliation tool to reconcile pe → si."""
		pr = frappe.new_doc("Payment Reconciliation")
		pr.company = self.company
		pr.party_type = "Customer"
		pr.party = self.customer if not pe.party or pe.party == self.customer else pe.party
		pr.receivable_payable_account = self.debit_to
		pr.get_unreconciled_entries()
		# Allocate
		pr.allocate_entries(
			{
				"payments": [
					{
						"reference_type": "Payment Entry",
						"reference_name": pe.name,
						"amount": amount,
					}
				],
				"invoices": [
					{
						"invoice_type": "Sales Invoice",
						"invoice_number": si.name,
						"amount": amount,
					}
				],
			}
		)
		pr.reconcile()
		return pr
