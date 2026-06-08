# Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class JournalEntryTemplate(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.journal_entry_template_account.journal_entry_template_account import (
			JournalEntryTemplateAccount,
		)

		accounts: DF.Table[JournalEntryTemplateAccount]
		allow_additional_accounts: DF.Check
		auto_reverse_date: DF.Date | None
		auto_reverse_on: DF.Literal["First Day of Next Month", "Specific Date"]
		auto_submit_reversal: DF.Check
		company: DF.Link
		disabled: DF.Check
		enable_auto_reversal: DF.Check
		end_date: DF.Date | None
		from_date: DF.Date | None
		is_opening: DF.Literal["No", "Yes"]
		lock_on_apply: DF.Check
		multi_currency: DF.Check
		naming_series: DF.Literal
		reversal_cost_center_mode: DF.Literal["Use Original", "Apply Current Allocation"]
		reversal_exchange_rate_type: DF.Literal["Original Rate", "Current Rate"]
		reversal_tax_mode: DF.Literal["Use Original", "Recalculate for Posting Date"]
		template_title: DF.Data
		voucher_type: DF.Literal[
			"Journal Entry",
			"Inter Company Journal Entry",
			"Bank Entry",
			"Cash Entry",
			"Credit Card Entry",
			"Debit Note",
			"Credit Note",
			"Contra Entry",
			"Excise Entry",
			"Write Off Entry",
			"Opening Entry",
			"Depreciation Entry",
			"Exchange Rate Revaluation",
		]
	# end: auto-generated types

	# Structural fields that are frozen once the template has been used by a
	# submitted Journal Entry (WP GA-0001-04, defect WA-0001-04 #1). Everything
	# not in this set — notably `disabled`, `from_date`, `end_date` — stays
	# editable so the template can be retired or date-bounded after lock.
	FROZEN_AFTER_USE = (
		"template_title",
		"voucher_type",
		"naming_series",
		"company",
		"is_opening",
		"multi_currency",
		"lock_on_apply",
		"allow_additional_accounts",
		"enable_auto_reversal",
		"auto_reverse_on",
		"auto_reverse_date",
		"reversal_exchange_rate_type",
		"reversal_tax_mode",
		"reversal_cost_center_mode",
		"auto_submit_reversal",
	)

	def onload(self):
		# Surface lock/enforcement state to the client without an extra round-trip.
		self.set_onload("in_use", self.is_in_use())
		self.set_onload(
			"enforce_template_field_locking",
			bool(
				frappe.db.get_single_value("Accounts Settings", "enforce_template_field_locking")
			),
		)

	def validate(self):
		self.enforce_global_lock_setting()
		self.validate_availability_dates()
		self.validate_party()
		self.validate_auto_reversal()
		self.guard_locked_after_use()

	def is_in_use(self):
		"""A template is "in use" once at least one submitted Journal Entry was
		created from it. Drafts are transient, so they do not lock the template."""
		if self.is_new():
			return False
		return bool(
			frappe.db.exists("Journal Entry", {"from_template": self.name, "docstatus": 1})
		)

	def enforce_global_lock_setting(self):
		# Defect WA-0001-04 #4 — when the global Accounts Settings switch is on,
		# Lock Fields on Apply cannot be turned off on any template.
		if frappe.db.get_single_value("Accounts Settings", "enforce_template_field_locking"):
			self.lock_on_apply = 1

	def validate_availability_dates(self):
		if self.from_date and self.end_date and getdate(self.from_date) > getdate(self.end_date):
			frappe.throw(_("From Date cannot be after End Date."))

	def guard_locked_after_use(self):
		# Defect WA-0001-04 #1 — once a template has produced a submitted Journal
		# Entry, its structure is frozen for audit. Only availability fields
		# (disabled / from_date / end_date) may still change.
		if self.is_new() or not self.is_in_use():
			return
		before = self.get_doc_before_save()
		if not before:
			return

		# When global enforcement is on, lock_on_apply is force-set to 1 by
		# enforce_global_lock_setting(); don't flag that forced change here.
		enforced = frappe.db.get_single_value("Accounts Settings", "enforce_template_field_locking")

		for field in self.FROZEN_AFTER_USE:
			if field == "lock_on_apply" and enforced:
				continue
			if (self.get(field) or None) != (before.get(field) or None):
				frappe.throw(
					_(
						"Journal Entry Template {0} has already been used by a submitted Journal Entry, so {1} can no longer be changed. You may still disable it or adjust its From/End dates."
					).format(frappe.bold(self.name), frappe.bold(_(self.meta.get_label(field) or field)))
				)

		if self._accounts_signature(self) != self._accounts_signature(before):
			frappe.throw(
				_(
					"Journal Entry Template {0} has already been used by a submitted Journal Entry, so its accounting entries can no longer be changed."
				).format(frappe.bold(self.name))
			)

	@staticmethod
	def _accounts_signature(doc):
		return [
			(
				row.get("account"),
				row.get("party_type") or None,
				row.get("party") or None,
				row.get("cost_center") or None,
				row.get("project") or None,
				flt(row.get("debit_in_account_currency")),
				flt(row.get("credit_in_account_currency")),
				row.get("user_remark") or None,
			)
			for row in doc.get("accounts", [])
		]

	def validate_party(self):
		"""
		Loop over all accounts and see if party and party type is set correctly
		"""
		for account in self.accounts:
			if account.party_type:
				account_type = frappe.get_cached_value("Account", account.account, "account_type")
				if account_type not in ["Receivable", "Payable"]:
					frappe.throw(
						_(
							"Check row {0} for account {1}: Party Type is only allowed for Receivable or Payable accounts"
						).format(account.idx, account.account)
					)

			if account.party and not account.party_type:
				frappe.throw(
					_("Check row {0} for account {1}: Party is only allowed if Party Type is set").format(
						account.idx, account.account
					)
				)

	def validate_auto_reversal(self):
		if not self.enable_auto_reversal:
			return
		if self.auto_reverse_on == "Specific Date" and not self.auto_reverse_date:
			frappe.throw(_("Reversal Date is required when Auto Reverse On is set to Specific Date."))
		if self.auto_reverse_on == "First Day of Next Month":
			self.auto_reverse_date = None


@frappe.whitelist()
def get_naming_series():
	return frappe.get_meta("Journal Entry").get_field("naming_series").options
