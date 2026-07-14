# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.utils import is_immutable_ledger_enabled, update_voucher_outstanding


class PaymentReconciliationEntry(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Link
		allocated_amount: DF.Currency
		amended_from: DF.Link | None
		base_allocated_amount: DF.Currency
		company: DF.Link
		cost_center: DF.Link | None
		currency: DF.Link | None
		exchange_gain_loss: DF.Currency
		exchange_gain_loss_journal: DF.Link | None
		exchange_rate: DF.Float
		finance_book: DF.Link | None
		invoice_name: DF.DynamicLink
		invoice_type: DF.Link
		is_reversal: DF.Check
		is_unreconciled: DF.Check
		party: DF.DynamicLink
		party_type: DF.Link
		payment_name: DF.DynamicLink
		posting_date: DF.Date | None
		payment_reference_row: DF.Data | None
		payment_type: DF.Link
		process_payment_reconciliation_log: DF.Link | None
		project: DF.Link | None
		reconciliation_date: DF.Date
		reversal_of: DF.Link | None
		unreconciled_by: DF.Link | None
		unreconciled_on: DF.Date | None
	# end: auto-generated types

	SUPPORTED_PAYMENT_TYPES = ("Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice")
	SUPPORTED_INVOICE_TYPES = ("Sales Invoice", "Purchase Invoice", "Journal Entry", "Payment Entry")

	def before_insert(self):
		# WP GA-0001-03: a Payment Reconciliation Entry is an accounting record
		# produced by the reconciliation engine — it must never be hand-created
		# from the desk. Both legitimate entry points (the Payment Reconciliation
		# tool via `_create_pre_for_allocation`, and Unreconcile Payment via
		# `_create_reversal_pre`) set this flag before inserting. Anything else
		# (manual "New", API insert) is rejected.
		if not self.flags.via_reconciliation_tool:
			frappe.throw(
				_(
					"Payment Reconciliation Entry cannot be created directly. "
					"Use the Payment Reconciliation tool to reconcile, or Unreconcile "
					"Payment to reverse an existing reconciliation."
				),
				title=_("Not Allowed"),
			)

	def validate(self):
		self._validate_payment_invoice_compatibility()
		self._set_currency_and_exchange_rate()
		self._compute_base_allocated_amount()
		if self.is_reversal:
			self._validate_reversal_target()
		# WP GA-0001-03 #11 / #1: the effective GL posting date is stored (and
		# shown) on the document rather than computed invisibly at GL time.
		self.posting_date = self._clearing_posting_date()

	def before_save(self):
		self._compute_base_allocated_amount()

	def on_submit(self):
		self._create_advance_payment_ledger_entry()
		self._post_clearing_gl_pair()
		if self.is_reversal:
			frappe.db.set_value(
				"Payment Reconciliation Entry",
				self.reversal_of,
				{
					"is_unreconciled": 1,
					"unreconciled_by": self.name,
					"unreconciled_on": self.reconciliation_date or nowdate(),
				},
				update_modified=False,
			)
			# Reversal nets the original recon's PLE rows to zero. Leaving both
			# rows live makes the AR / aged-receivables aggregator double-count
			# them into the invoiced / paid buckets — outstanding stays right
			# but the breakdown is misleading. Mark both vouchers' PLE rows as
			# `delinked=1` so the report skips them. GL Entry rows stay intact
			# for audit.
			frappe.db.sql(
				"""
				update `tabPayment Ledger Entry`
				set delinked=1, modified=%(now)s
				where voucher_type='Payment Reconciliation Entry'
				  and voucher_no in (%(orig)s, %(rev)s)
				""",
				{"now": frappe.utils.now(), "orig": self.reversal_of, "rev": self.name},
			)
			# WP GA-0001-03 #4 (client-confirmed design): the PE Reference row
			# added by the original recon is neither deleted nor zeroed on
			# unreconcile. Its recorded values (allocated amount, exchange rate,
			# account) are preserved verbatim for audit; the row is flagged
			# `is_reversed=1` and carries links to BOTH reconciliation entries —
			# `reconciliation_entry` (the original PRE, set at recon time) and
			# `reversal_reconciliation_entry` (this reversal PRE). Preserving the
			# amount is safe under Immutable Ledger because the submitted PE's
			# stored totals are never recomputed from its reference rows
			# post-submit (the PE is not saved by the PRE flow), and payment
			# availability in the reconciliation tool is derived from PRE state,
			# not from these rows.
			if self.payment_type == "Payment Entry":
				orig_ref_row = frappe.db.get_value(
					"Payment Reconciliation Entry",
					self.reversal_of,
					"payment_reference_row",
				)
				if orig_ref_row and frappe.db.exists(
					"Payment Entry Reference", orig_ref_row
				):
					frappe.db.set_value(
						"Payment Entry Reference",
						orig_ref_row,
						{
							"is_reversed": 1,
							"reversal_reconciliation_entry": self.name,
						},
						update_modified=False,
					)
			# WP GA-0001-03 #7: the exchange gain/loss JE booked by the original
			# reconciliation must be REVERSED on unreconcile, not cancelled or
			# left orphaned. Post a GA-0001-01 reversal JE that offsets it; both
			# the original and the reversal stay docstatus=1 for the immutable
			# audit trail.
			self._reverse_exchange_gain_loss_journal()
		else:
			if self.payment_type == "Payment Entry" and self.payment_reference_row:
				frappe.db.set_value(
					"Payment Entry Reference",
					self.payment_reference_row,
					"reconciliation_entry",
					self.name,
					update_modified=False,
				)
		self._update_voucher_outstanding()

	def on_cancel(self):
		if is_immutable_ledger_enabled():
			frappe.throw(
				_(
					"Cannot cancel a Payment Reconciliation Entry under Immutable Ledger. "
					"Use Unreconcile Payment to reverse this reconciliation."
				)
			)
		# Legacy IM-OFF cancel: reverse-link the PE Reference and let standard
		# GL reverse-posting handle the clearing pair.
		if (
			not self.is_reversal
			and self.payment_type == "Payment Entry"
			and self.payment_reference_row
		):
			frappe.db.set_value(
				"Payment Entry Reference",
				self.payment_reference_row,
				"reconciliation_entry",
				None,
				update_modified=False,
			)

	# --- helpers ---

	def _reverse_exchange_gain_loss_journal(self):
		"""WP GA-0001-03 #7 — reverse, don't cancel, the exchange gain/loss JE.

		On unreconcile (this is a reversal PRE), the system-generated
		``Exchange Gain Or Loss`` JE that the original reconciliation booked
		must be offset by a GA-0001-01 reversal JE rather than cancelled or
		left orphaned. The original JE stays docstatus=1; the reversal JE
		(``is_reversal=1``, ``reversal_of`` = original) flips its debits and
		credits and is linked on this reversal PRE's
		``exchange_gain_loss_journal``. Idempotent — a no-op when the original
		recon had no gain/loss JE or one has already been reversed.
		"""
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		orig_je = frappe.db.get_value(
			"Payment Reconciliation Entry", self.reversal_of, "exchange_gain_loss_journal"
		)
		if not orig_je or frappe.db.get_value("Journal Entry", orig_je, "docstatus") != 1:
			return
		# Already reversed (e.g. re-run) — don't double-post.
		if frappe.db.exists("Journal Entry", {"reversal_of": orig_je, "docstatus": ["in", [0, 1]]}):
			return

		rev_je = make_reverse_journal_entry(orig_je)
		# Post the reversal on the unreconcile date and keep it flagged as a
		# system entry (the audit lookups filter on is_system_generated=1).
		rev_je.posting_date = self.reconciliation_date
		rev_je.is_system_generated = 1
		rev_je.flags.ignore_permissions = True
		rev_je.insert()
		rev_je.submit()
		frappe.db.set_value(
			"Payment Reconciliation Entry",
			self.name,
			"exchange_gain_loss_journal",
			rev_je.name,
			update_modified=False,
		)

	def _validate_payment_invoice_compatibility(self):
		if self.payment_type not in self.SUPPORTED_PAYMENT_TYPES:
			frappe.throw(
				_("Payment Type {0} is not supported by Payment Reconciliation Entry").format(
					frappe.bold(self.payment_type)
				)
			)
		if self.invoice_type not in self.SUPPORTED_INVOICE_TYPES:
			frappe.throw(
				_("Invoice Type {0} is not supported by Payment Reconciliation Entry").format(
					frappe.bold(self.invoice_type)
				)
			)
		if not self.party_type or not self.party:
			frappe.throw(_("Party Type and Party are required"))
		if flt(self.allocated_amount) <= 0:
			frappe.throw(_("Allocated Amount must be greater than zero"))

	def _set_currency_and_exchange_rate(self):
		if not self.currency and self.account:
			self.currency = frappe.get_cached_value("Account", self.account, "account_currency")
		if not self.exchange_rate:
			self.exchange_rate = 1

	def _compute_base_allocated_amount(self):
		self.base_allocated_amount = flt(
			flt(self.allocated_amount) * flt(self.exchange_rate),
			self.precision("base_allocated_amount"),
		)

	def _validate_reversal_target(self):
		if not self.reversal_of:
			frappe.throw(_("Reversal entries must specify Reversal Of"))
		target = frappe.db.get_value(
			"Payment Reconciliation Entry",
			self.reversal_of,
			["docstatus", "is_reversal", "is_unreconciled"],
			as_dict=True,
		)
		if not target:
			frappe.throw(_("Reversal target {0} does not exist").format(self.reversal_of))
		if target.docstatus != 1:
			frappe.throw(_("Reversal target {0} must be submitted").format(self.reversal_of))
		if target.is_reversal:
			frappe.throw(_("Cannot reverse a reversal entry"))
		if target.is_unreconciled:
			frappe.throw(_("Reversal target {0} is already unreconciled").format(self.reversal_of))
		# WP GA-0001-03 #12: the user may choose the unreconcile date, but the
		# reversal must not post before the original clearing GL — that would
		# corrupt period balances between the two dates.
		orig_posting_date = frappe.db.get_value(
			"Payment Reconciliation Entry",
			self.reversal_of,
			["posting_date", "reconciliation_date"],
			as_dict=True,
		)
		floor_date = orig_posting_date.posting_date or orig_posting_date.reconciliation_date
		if floor_date and self.reconciliation_date and getdate(self.reconciliation_date) < getdate(floor_date):
			frappe.throw(
				_("Unreconcile Date {0} cannot be before the original reconciliation's posting date {1}").format(
					frappe.bold(self.reconciliation_date), frappe.bold(floor_date)
				)
			)

	def _create_advance_payment_ledger_entry(self):
		"""Insert an APLE row marking the reconcile (or its reversal).

		The amount is signed: positive on the original PRE, negative on a
		reversal PRE. `event="Reconcile"` distinguishes these from PE/JE-submit
		APLE rows.
		"""
		amount_sign = -1 if self.is_reversal else 1
		amount = amount_sign * flt(self.allocated_amount)
		base_amount = amount_sign * flt(self.base_allocated_amount)

		aple = frappe.get_doc(
			{
				"doctype": "Advance Payment Ledger Entry",
				"company": self.company,
				"voucher_type": self.payment_type,
				"voucher_no": self.payment_name,
				"against_voucher_type": self.invoice_type,
				"against_voucher_no": self.invoice_name,
				"currency": self.currency,
				"exchange_rate": self.exchange_rate,
				"amount": amount,
				"base_amount": base_amount,
				"event": "Reconcile",
				"is_reversal": 1 if self.is_reversal else 0,
				"reversal_of": None,
				"payment_reconciliation_entry": self.name,
			}
		)
		aple.flags.ignore_permissions = True
		aple.insert()

	def _update_voucher_outstanding(self):
		update_voucher_outstanding(
			self.invoice_type,
			self.invoice_name,
			self.account,
			self.party_type,
			self.party,
		)
		# When the payment side is itself a Sales/Purchase Invoice (the
		# credit/debit note recon flow — GAP-013), its `outstanding_amount`
		# also needs refreshing. PE/JE payments don't have an outstanding
		# field that needs this maintenance.
		if self.payment_type in ("Sales Invoice", "Purchase Invoice"):
			update_voucher_outstanding(
				self.payment_type,
				self.payment_name,
				self.account,
				self.party_type,
				self.party,
			)

	# --- clearing GL ---

	def _resolve_clearing_accounts(self):
		"""Returns (advance_account, dr_or_cr_for_invoice_side).

		For a customer Receive PE: invoice side credits (CR), advance debits (DR).
		For a supplier Pay PE: invoice side debits (DR), advance credits (CR).
		"""
		invoice_account = self.account  # the receivable / payable on the invoice
		if self.payment_type == "Payment Entry":
			pe = frappe.get_cached_doc("Payment Entry", self.payment_name)
			advance_account = pe.party_account
			if pe.payment_type == "Receive":
				dr_or_cr_invoice = "credit"
			else:
				dr_or_cr_invoice = "debit"
		elif self.payment_type == "Journal Entry":
			# JE-as-payment: read the JE Account row this PRE references.
			advance_account = invoice_account
			if self.payment_reference_row:
				row = frappe.db.get_value(
					"Journal Entry Account",
					self.payment_reference_row,
					["account", "debit_in_account_currency", "credit_in_account_currency"],
					as_dict=True,
				)
				if row:
					advance_account = row.account
					dr_or_cr_invoice = "credit" if flt(row.debit_in_account_currency) else "debit"
				else:
					dr_or_cr_invoice = "credit" if self.party_type == "Customer" else "debit"
			else:
				dr_or_cr_invoice = "credit" if self.party_type == "Customer" else "debit"
		else:
			# Sales/Purchase Invoice as payment (dr/cr note flow): treat invoice
			# side as the receivable/payable and the "advance" side as the note's
			# corresponding account on Account.
			advance_account = invoice_account
			dr_or_cr_invoice = "credit" if self.party_type == "Customer" else "debit"
		return advance_account, dr_or_cr_invoice

	def _clearing_posting_date(self):
		"""WP GA-0001-03 #11 — posting date for the clearing GL pair.

		The forward reconciliation honours the Company's "Reconciliation Takes
		Effect On" policy (Advance Payment Date / Oldest Of Invoice Or Advance /
		Reconciliation Date) via ``get_reconciliation_effect_date`` — previously
		the clearing GL always posted on the reconcile date, ignoring the policy.
		Under the "Reconciliation Date" policy the user-chosen
		``reconciliation_date`` is used (so the editable date from #1 still
		drives posting when the policy selects it). A reversal PRE posts on its
		own (unreconcile) date, so undoing a reconcile never posts into a
		possibly-closed prior period.
		"""
		if self.is_reversal:
			return self.reconciliation_date
		from erpnext.accounts.utils import get_reconciliation_effect_date

		payment_posting_date = frappe.db.get_value(
			self.payment_type, self.payment_name, "posting_date"
		)
		return get_reconciliation_effect_date(
			self.invoice_type,
			self.invoice_name,
			self.company,
			payment_posting_date or self.reconciliation_date,
			self.reconciliation_date,
		)

	def _post_clearing_gl_pair(self):
		from erpnext.accounts.general_ledger import make_gl_entries

		advance_account, dr_or_cr_invoice = self._resolve_clearing_accounts()
		if self.is_reversal:
			# Swap directions on reversal so the GL pair offsets the original.
			dr_or_cr_invoice = "debit" if dr_or_cr_invoice == "credit" else "credit"
		dr_or_cr_advance = "debit" if dr_or_cr_invoice == "credit" else "credit"

		base_amount = flt(self.base_allocated_amount)
		alloc_amount = flt(self.allocated_amount)

		common = {
			"company": self.company,
			"posting_date": self.posting_date or self._clearing_posting_date(),
			"voucher_type": "Payment Reconciliation Entry",
			"voucher_no": self.name,
			"voucher_detail_no": self.payment_reference_row,
			"party_type": self.party_type,
			"party": self.party,
			"cost_center": self.cost_center,
			"project": self.project,
			"finance_book": self.finance_book,
			"remarks": _("Payment Reconciliation Entry {0}").format(self.name),
		}

		# Invoice side row
		invoice_row = {**common}
		invoice_row["account"] = self.account
		invoice_row[dr_or_cr_invoice] = base_amount
		invoice_row[dr_or_cr_invoice + "_in_account_currency"] = alloc_amount
		invoice_row.update(
			{
				"against_voucher_type": self.invoice_type,
				"against_voucher": self.invoice_name,
			}
		)

		# Advance side row
		advance_row = {**common}
		advance_row["account"] = advance_account
		advance_row[dr_or_cr_advance] = base_amount
		advance_row[dr_or_cr_advance + "_in_account_currency"] = alloc_amount
		advance_row.update(
			{
				"against_voucher_type": self.payment_type,
				"against_voucher": self.payment_name,
			}
		)

		gl_entries = [self._make_gl_dict(invoice_row), self._make_gl_dict(advance_row)]
		make_gl_entries(gl_entries, update_outstanding="No", merge_entries=False)

	def _make_gl_dict(self, args):
		# Mirrors the minimal shape get_gl_dict produces. We avoid get_gl_dict
		# directly because that is a Document method on transaction docs and
		# pulls fields like cost_center defaults from `item` — we already have
		# everything we need on `self`. Returns frappe._dict so the downstream
		# make_gl_entries pipeline can attribute-access fields like .voucher_type.
		# account_currency is derived from the row's account (not self.currency)
		# because the invoice and advance accounts may be in different currencies.
		account_currency = frappe.get_cached_value(
			"Account", args.get("account"), "account_currency"
		) if args.get("account") else self.currency
		out = frappe._dict({
			"account": args.get("account"),
			"debit": args.get("debit", 0),
			"credit": args.get("credit", 0),
			"debit_in_account_currency": args.get("debit_in_account_currency", 0),
			"credit_in_account_currency": args.get("credit_in_account_currency", 0),
			"account_currency": account_currency,
			"company": args["company"],
			"posting_date": args["posting_date"],
			"voucher_type": args["voucher_type"],
			"voucher_no": args["voucher_no"],
			"voucher_detail_no": args.get("voucher_detail_no"),
			"party_type": args.get("party_type"),
			"party": args.get("party"),
			"cost_center": args.get("cost_center"),
			"project": args.get("project"),
			"finance_book": args.get("finance_book"),
			"against_voucher_type": args.get("against_voucher_type"),
			"against_voucher": args.get("against_voucher"),
			"remarks": args.get("remarks"),
			"is_advance": "No",
		})
		return out

