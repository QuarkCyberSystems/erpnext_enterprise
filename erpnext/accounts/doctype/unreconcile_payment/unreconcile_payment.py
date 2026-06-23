# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _, qb
from frappe.model.document import Document
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Abs, Sum
from frappe.utils.data import comma_and

from erpnext.accounts.utils import (
	cancel_exchange_gain_loss_journal,
	is_immutable_ledger_enabled,
	unlink_ref_doc_from_payment_entries,
	update_voucher_outstanding,
)


class UnreconcilePayment(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.unreconcile_payment_entries.unreconcile_payment_entries import (
			UnreconcilePaymentEntries,
		)

		allocations: DF.Table[UnreconcilePaymentEntries]
		amended_from: DF.Link | None
		company: DF.Link | None
		voucher_no: DF.DynamicLink | None
		voucher_type: DF.Link | None
	# end: auto-generated types

	def before_insert(self):
		# WP GA-0001-03 #9: Unreconcile Payment is a ledger-altering action
		# record — submitting it reverses reconciliations (creates reversal
		# PREs under Immutable Ledger). It must only be raised by the UnReconcile
		# action flow (`create_unreconcile_doc_for_selection`), which sets this
		# flag. A hand-created doc from the desk / API is rejected, mirroring the
		# Payment Reconciliation Entry lockdown.
		if not self.flags.via_unreconcile_action:
			frappe.throw(
				_(
					"Unreconcile Payment cannot be created directly. Use the "
					"UnReconcile action on the Payment Entry / Journal Entry / Invoice."
				),
				title=_("Not Allowed"),
			)

	def validate(self):
		# WP GA-0001-03 / GAP-013: under Immutable Ledger, credit/debit notes
		# (Sales/Purchase Invoice with is_return=1) route through PRE just
		# like PE/JE — so they must also be unreconcilable. Adding them
		# unconditionally is safe: the IM-OFF path still uses
		# `reconcile_dr_cr_note` which creates a system JE that's cancelled
		# directly (no Unreconcile Payment doc is generated for it), so
		# expanding the allowlist doesn't change legacy behaviour.
		self.supported_types = ["Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice"]
		if self.voucher_type not in self.supported_types:
			frappe.throw(_("Only {0} are supported").format(comma_and(self.supported_types)))

	@frappe.whitelist()
	def get_allocations_from_payment(self):
		return get_linked_payments_for_doc(
			company=self.company,
			doctype=self.voucher_type,
			docname=self.voucher_no,
		)

	def add_references(self):
		allocations = self.get_allocations_from_payment()

		for alloc in allocations:
			self.append("allocations", alloc)

	def on_submit(self):
		# todo: more granular unreconciliation
		immutable = is_immutable_ledger_enabled()
		for alloc in self.allocations:
			reversal_pre = None
			if immutable:
				original_pre = frappe.db.get_value(
					"Payment Reconciliation Entry",
					{
						"payment_type": self.voucher_type,
						"payment_name": self.voucher_no,
						"invoice_type": alloc.reference_doctype,
						"invoice_name": alloc.reference_name,
						"is_reversal": 0,
						"is_unreconciled": 0,
						"docstatus": 1,
					},
					"name",
				)
				if original_pre:
					reversal_pre = self._create_reversal_pre(original_pre)
			else:
				doc = frappe.get_doc(alloc.reference_doctype, alloc.reference_name)
				unlink_ref_doc_from_payment_entries(doc, self.voucher_no)
				cancel_exchange_gain_loss_journal(doc, self.voucher_type, self.voucher_no)

			# update outstanding amounts
			update_voucher_outstanding(
				alloc.reference_doctype,
				alloc.reference_name,
				alloc.account,
				alloc.party_type,
				alloc.party,
			)

			frappe.db.set_value(
				"Unreconcile Payment Entries",
				alloc.name,
				{"unlinked": True, "reversal_pre": reversal_pre.name if reversal_pre else None},
				update_modified=False,
			)

	def _create_reversal_pre(self, original_pre_name):
		"""Create + submit a reversal Payment Reconciliation Entry.

		Copies the original PRE, flips is_reversal=1, sets reversal_of, and
		resets the unreconcile audit fields. Submitting the reversal PRE
		posts a swap GL pair (Commit 6) and `db_set`s is_unreconciled=1
		on the original (Commit 5 on_submit).
		"""
		src = frappe.get_doc("Payment Reconciliation Entry", original_pre_name)
		reversal = frappe.copy_doc(src)
		reversal.is_reversal = 1
		reversal.reversal_of = original_pre_name
		from frappe.utils import nowdate

		reversal.reconciliation_date = nowdate()
		reversal.is_unreconciled = 0
		reversal.unreconciled_by = None
		reversal.unreconciled_on = None
		reversal.amended_from = None
		# copy_doc inherits the original's exchange_gain_loss_journal link.
		# Reversal PREs don't post their own gain/loss JE under the current
		# WP-03 design (the original JE is preserved per GAP-010); leaving
		# the link inherited makes it look like the reversal "owns" the JE,
		# which it doesn't. Clear it to keep the data model honest.
		reversal.exchange_gain_loss_journal = None
		reversal.flags.ignore_permissions = True
		# Authorise creation: PRE rejects any insert not originating from the
		# reconciliation engine (see PaymentReconciliationEntry.before_insert).
		reversal.flags.via_reconciliation_tool = True
		reversal.insert()
		reversal.submit()
		return reversal


@frappe.whitelist()
def doc_has_references(doctype: str | None = None, docname: str | None = None):
	count = 0
	# WP GA-0001-03 / GAP-013: credit/debit notes (Sales/Purchase Invoice
	# with is_return=1) act as the PAYMENT side of a PRE under Immutable
	# Ledger. Their references live as PREs where `payment_name=this doc`,
	# not as inbound PLE rows on the invoice-side. Route them through the
	# payment-side check so the button only appears when there's an actual
	# active recon to undo.
	is_return_invoice = (
		doctype in ("Sales Invoice", "Purchase Invoice")
		and (frappe.db.get_value(doctype, docname, "is_return") or 0)
	)
	if doctype in ["Sales Invoice", "Purchase Invoice"] and not is_return_invoice:
		count = frappe.db.count(
			"Payment Ledger Entry",
			filters={
				"delinked": 0,
				"against_voucher_no": docname,
				"voucher_no": ["!=", docname],  # exclude the invoice's own submit row
				"amount": ["<", 0],
			},
		)
	else:
		count = frappe.db.count(
			"Payment Ledger Entry",
			filters={"delinked": 0, "voucher_no": docname, "against_voucher_no": ["!=", docname]},
		)
		# WP GA-0001-03: under bapsp + Immutable Ledger, reconciliation creates
		# an APLE row with event='Reconcile' rather than mutating the original
		# Submit row. Treat either as a "live reference" so the UnReconcile
		# action remains discoverable on reconciled PEs under that flow.
		count += frappe.db.count(
			"Advance Payment Ledger Entry",
			filters={
				"delinked": 0,
				"voucher_no": docname,
				"voucher_type": doctype,
				"event": ["in", ["Submit", "Reconcile"]],
			},
		)

	return count


@frappe.whitelist()
def get_linked_payments_for_doc(
	company: str | None = None, doctype: str | None = None, docname: str | None = None
) -> list:
	if company and doctype and docname:
		_dt = doctype
		_dn = docname
		ple = qb.DocType("Payment Ledger Entry")
		# WP GA-0001-03 / GAP-013: a Sales/Purchase Invoice with is_return=1
		# is a credit/debit note acting as a PAYMENT in a PRE recon. It
		# should be looked up via the payment-side query (find PREs where
		# payment_name = this doc), NOT the invoice-side query.
		_is_return_invoice = (
			_dt in ("Sales Invoice", "Purchase Invoice")
			and (frappe.db.get_value(_dt, _dn, "is_return") or 0)
		)
		if _dt in ["Sales Invoice", "Purchase Invoice"] and not _is_return_invoice:
			criteria = [
				(ple.company == company),
				(ple.delinked == 0),
				(ple.against_voucher_no == _dn),
				(ple.amount < 0),
			]

			res = (
				qb.from_(ple)
				.select(
					ple.account,
					ple.party_type,
					ple.party,
					ple.company,
					ple.voucher_type.as_("reference_doctype"),
					ple.voucher_no.as_("reference_name"),
					Abs(Sum(ple.amount_in_account_currency)).as_("allocated_amount"),
					ple.account_currency,
				)
				.where(Criterion.all(criteria))
				.groupby(ple.voucher_no, ple.against_voucher_no)
				.having(qb.Field("allocated_amount") > 0)
				.run(as_dict=True)
			)

			# WP GA-0001-03: under Immutable Ledger the clearing GL/PLE pair is
			# owned by the Payment Reconciliation Entry, so the rows above surface
			# the PRE itself as the "payment" — which Unreconcile Payment can't act
			# on (PRE isn't an allowed voucher_type). Resolve those PRE rows back to
			# the real payment voucher, mirroring the payment-side logic below.
			if is_immutable_ledger_enabled():
				res = [r for r in res if r.get("reference_doctype") != "Payment Reconciliation Entry"]
				existing_pairs = {(r.get("reference_doctype"), r.get("reference_name")) for r in res}
				pre_rows = frappe.get_all(
					"Payment Reconciliation Entry",
					filters={
						"company": company,
						"invoice_type": _dt,
						"invoice_name": _dn,
						"is_reversal": 0,
						"is_unreconciled": 0,
						"docstatus": 1,
					},
					fields=[
						"company",
						"account",
						"party_type",
						"party",
						"payment_type as reference_doctype",
						"payment_name as reference_name",
						"allocated_amount",
						"currency as account_currency",
					],
				)
				for row in pre_rows:
					if (row.reference_doctype, row.reference_name) not in existing_pairs:
						res.append(row)

			return res
		else:
			criteria = [
				(ple.company == company),
				(ple.delinked == 0),
				(ple.voucher_no == _dn),
				(ple.against_voucher_no != _dn),
			]

			query = (
				qb.from_(ple)
				.select(
					ple.company,
					ple.account,
					ple.party_type,
					ple.party,
					ple.against_voucher_type.as_("reference_doctype"),
					ple.against_voucher_no.as_("reference_name"),
					Abs(Sum(ple.amount_in_account_currency)).as_("allocated_amount"),
					ple.account_currency,
				)
				.where(Criterion.all(criteria))
				.groupby(ple.against_voucher_no)
			)

			res = query.run(as_dict=True)

			res += get_linked_advances(company, _dn)

			# Under Immutable Ledger, PE → invoice linkage lives in PRE, not in PLE
			# (the PRE owns the clearing GL pair, the PE's own PLE only points to the
			# advance account). Pull active (non-reversed, non-unreconciled) PREs
			# whose payment_name == this PE and add them as reference rows.
			if is_immutable_ledger_enabled():
				existing_pairs = {(r.get("reference_doctype"), r.get("reference_name")) for r in res}
				pre_rows = frappe.get_all(
					"Payment Reconciliation Entry",
					filters={
						"company": company,
						"payment_name": _dn,
						"is_reversal": 0,
						"is_unreconciled": 0,
						"docstatus": 1,
					},
					fields=[
						"company",
						"account",
						"party_type",
						"party",
						"invoice_type as reference_doctype",
						"invoice_name as reference_name",
						"allocated_amount",
						"currency as account_currency",
					],
				)
				for row in pre_rows:
					if (row.reference_doctype, row.reference_name) not in existing_pairs:
						res.append(row)

			return res

	return []


def get_linked_advances(company, docname):
	adv = qb.DocType("Advance Payment Ledger Entry")
	criteria = [
		(adv.company == company),
		(adv.delinked == 0),
		(adv.voucher_no == docname),
		(adv.event == "Submit"),
	]

	return (
		qb.from_(adv)
		.select(
			adv.company,
			adv.against_voucher_type.as_("reference_doctype"),
			adv.against_voucher_no.as_("reference_name"),
			Abs(Sum(adv.amount)).as_("allocated_amount"),
			adv.currency,
		)
		.where(Criterion.all(criteria))
		.having(qb.Field("allocated_amount") > 0)
		.groupby(adv.against_voucher_no)
		.run(as_dict=True)
	)


@frappe.whitelist()
def create_unreconcile_doc_for_selection(selections=None):
	if selections:
		selections = json.loads(selections)
		# assuming each row is a unique voucher
		for row in selections:
			voucher_type = row.get("voucher_type")
			voucher_no = row.get("voucher_no")
			against_type = row.get("against_voucher_type")
			against_no = row.get("against_voucher_no")

			# WP GA-0001-03 #6: a credit/debit note (Sales/Purchase Invoice with
			# is_return=1) is the PAYMENT side of its reconciliation — the PRE
			# stores it as `payment_name`, with the normal invoice as
			# `invoice_name`. When the user unreconciles from the note, the
			# selection can arrive with the note as `against` and the linked
			# invoice as `voucher` (the note is a Sales/Purchase Invoice doctype,
			# so it gets the invoice-side mapping). Left as-is, Unreconcile
			# Payment.on_submit looks up a PRE keyed on payment_name=voucher_no /
			# invoice_name=against_no — i.e. swapped — finds nothing, and silently
			# no-ops. Orient so the return invoice is always the voucher (payment)
			# and the normal invoice the counterparty. Idempotent: when the voucher
			# is already the return invoice (unreconcile from the invoice side, or
			# corrected JS), the condition is false and nothing is swapped.
			if (
				voucher_type in ("Sales Invoice", "Purchase Invoice")
				and against_type in ("Sales Invoice", "Purchase Invoice")
				and not frappe.db.get_value(voucher_type, voucher_no, "is_return")
				and frappe.db.get_value(against_type, against_no, "is_return")
			):
				voucher_type, against_type = against_type, voucher_type
				voucher_no, against_no = against_no, voucher_no

			unrecon = frappe.new_doc("Unreconcile Payment")
			# Authorise creation: Unreconcile Payment rejects any insert not
			# raised through this action flow (see before_insert).
			unrecon.flags.via_unreconcile_action = True
			unrecon.flags.ignore_permissions = True
			unrecon.company = row.get("company")
			unrecon.voucher_type = voucher_type
			unrecon.voucher_no = voucher_no
			unrecon.add_references()

			# remove unselected references
			unrecon.allocations = [
				x
				for x in unrecon.allocations
				if x.reference_doctype == against_type and x.reference_name == against_no
			]
			unrecon.save().submit()
