# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate

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

	def validate(self):
		self._validate_payment_invoice_compatibility()
		self._set_currency_and_exchange_rate()
		self._compute_base_allocated_amount()
		if self.is_reversal:
			self._validate_reversal_target()

	def before_save(self):
		self._compute_base_allocated_amount()

	def on_submit(self):
		self._create_advance_payment_ledger_entry()
		# Clearing GL pair posted in a follow-up commit (_post_clearing_gl_pair).
		if self.is_reversal:
			frappe.db.set_value(
				"Payment Reconciliation Entry",
				self.reversal_of,
				{
					"is_unreconciled": 1,
					"unreconciled_by": self.name,
					"unreconciled_on": nowdate(),
				},
				update_modified=False,
			)
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
