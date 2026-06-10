# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import json

import frappe
from frappe import _, msgprint, scrub
from frappe.core.doctype.submission_queue.submission_queue import queue_submission
from frappe.utils import comma_and, cstr, flt, fmt_money, formatdate, get_link_to_form, getdate, nowdate

import erpnext
from erpnext.accounts.deferred_revenue import get_deferred_booking_accounts
from erpnext.accounts.doctype.invoice_discounting.invoice_discounting import (
	get_party_account_based_on_invoice_discounting,
)
from erpnext.accounts.doctype.repost_accounting_ledger.repost_accounting_ledger import (
	validate_docs_for_deferred_accounting,
	validate_docs_for_voucher_types,
)
from erpnext.accounts.doctype.tax_withholding_entry.tax_withholding_entry import JournalTaxWithholding
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import (
	cancel_exchange_gain_loss_journal,
	get_account_currency,
	get_advance_payment_doctypes,
	get_balance_on,
	get_stock_accounts,
	get_stock_and_account_balance,
)
from erpnext.assets.doctype.asset_depreciation_schedule.asset_depreciation_schedule import (
	get_depr_schedule,
)
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.setup.utils import get_exchange_rate as _get_exchange_rate


class StockAccountInvalidTransaction(frappe.ValidationError):
	pass


class JournalEntry(AccountsController):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.journal_entry_account.journal_entry_account import JournalEntryAccount
		from erpnext.accounts.doctype.tax_withholding_entry.tax_withholding_entry import TaxWithholdingEntry

		accounts: DF.Table[JournalEntryAccount]
		amended_from: DF.Link | None
		apply_tds: DF.Check
		auto_repeat: DF.Link | None
		auto_reversal_status: DF.Data | None
		auto_reverse_date: DF.Date | None
		auto_reverse_on: DF.Literal["First Day of Next Month", "Specific Date"]
		auto_submit_reversal: DF.Check
		bill_date: DF.Date | None
		bill_no: DF.Data | None
		cheque_date: DF.Date | None
		cheque_no: DF.Data | None
		clearance_date: DF.Date | None
		company: DF.Link
		custom_remark: DF.Check
		difference: DF.Currency
		due_date: DF.Date | None
		enable_auto_reversal: DF.Check
		finance_book: DF.Link | None
		for_all_stock_asset_accounts: DF.Check
		from_template: DF.Link | None
		ignore_tax_withholding_threshold: DF.Check
		inter_company_journal_entry_reference: DF.Link | None
		is_opening: DF.Literal["No", "Yes"]
		is_reversal: DF.Check
		is_reversed: DF.Check
		is_system_generated: DF.Check
		letter_head: DF.Link | None
		linked_auto_repeat: DF.Link | None
		mode_of_payment: DF.Link | None
		multi_currency: DF.Check
		naming_series: DF.Literal["ACC-JV-.YYYY.-"]
		override_tax_withholding_entries: DF.Check
		party_not_required: DF.Check
		pay_to_recd_from: DF.Data | None
		payment_order: DF.Link | None
		periodic_entry_difference_account: DF.Link | None
		posting_date: DF.Date
		process_deferred_accounting: DF.Link | None
		remark: DF.SmallText | None
		respect_cost_center_allocation: DF.Check
		reversal_cost_center_mode: DF.Literal["Use Original", "Apply Current Allocation"]
		reversal_exchange_rate_type: DF.Literal["Original Rate", "Current Rate"]
		reversal_of: DF.Link | None
		reversal_tax_mode: DF.Literal["Use Original", "Recalculate for Posting Date"]
		reversed_by: DF.Link | None
		select_print_heading: DF.Link | None
		stock_asset_account: DF.Link | None
		stock_entry: DF.Link | None
		tax_withholding_category: DF.Link | None
		tax_withholding_entries: DF.Table[TaxWithholdingEntry]
		tax_withholding_group: DF.Link | None
		template_applied: DF.Check
		title: DF.Data | None
		total_amount: DF.Currency
		total_amount_currency: DF.Link | None
		total_amount_in_words: DF.Data | None
		total_credit: DF.Currency
		total_debit: DF.Currency
		user_remark: DF.SmallText | None
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
			"Asset Disposal",
			"Periodic Accounting Entry",
			"Exchange Rate Revaluation",
			"Exchange Gain Or Loss",
			"Deferred Revenue",
			"Deferred Expense",
		]
		write_off_amount: DF.Currency
		write_off_based_on: DF.Literal["Accounts Receivable", "Accounts Payable"]
	# end: auto-generated types

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def validate(self):
		if self.voucher_type == "Opening Entry":
			self.is_opening = "Yes"

		if not self.is_opening:
			self.is_opening = "No"

		self.clearance_date = None

		self.validate_party()
		self.validate_entries_for_advance()
		self.validate_multi_currency()
		self.set_amounts_in_company_currency()
		self.validate_debit_credit_amount()
		self.set_total_debit_credit()

		if not frappe.flags.is_reverse_depr_entry:
			self.validate_against_jv()
			self.validate_stock_accounts()

		self.validate_reference_doc()
		if self.docstatus == 0:
			self.set_against_account()
		self.create_remarks()
		self.set_print_format_fields()
		self.validate_credit_debit_note()
		self.validate_empty_accounts_table()
		self.validate_inter_company_accounts()
		self.validate_depr_account_and_depr_entry_voucher_type()
		self.validate_company_in_accounting_dimension()
		self.validate_advance_accounts()
		self.validate_template_availability()
		self.validate_against_template()
		self.validate_auto_reversal_config()

		JournalTaxWithholding(self).on_validate()

		self.validate_reversal_locked_fields()
		self.validate_reversal_totals_match_original()
		self.maybe_reresolve_cost_center()

		if self.is_new() or not self.title:
			self.title = self.get_title()

	def before_save(self):
		if self.is_new():
			return
		old = self.get_doc_before_save()
		if old and old.from_template and not self.from_template:
			self.template_applied = 0
			for row in self.accounts:
				row.from_template = 0

	def validate_auto_reversal_config(self):
		# WA-0001-05 #9 — keep the JE's auto-reversal config coherent whether it was
		# set manually or inherited from a template.
		if not self.enable_auto_reversal:
			self.auto_reverse_date = None
			return
		if self.auto_reverse_on == "First Day of Next Month":
			self.auto_reverse_date = None
		elif self.auto_reverse_on == "Specific Date" and not self.auto_reverse_date:
			frappe.throw(_("Reversal Date is required when Auto Reverse On is set to Specific Date."))

	def validate_template_availability(self):
		# Defect WA-0001-04 #2 — a disabled or out-of-date-range template cannot
		# be applied to a Journal Entry. Enforced for drafts only so historical
		# submitted entries are never blocked retroactively if the template is
		# later disabled or date-bounded.
		if self.docstatus != 0 or not self.from_template:
			return
		template = frappe.db.get_value(
			"Journal Entry Template",
			self.from_template,
			["disabled", "from_date", "end_date"],
			as_dict=True,
		)
		if not template:
			return

		link = get_link_to_form("Journal Entry Template", self.from_template)
		if template.disabled:
			frappe.throw(_("Journal Entry Template {0} is disabled and cannot be used.").format(link))

		posting_date = getdate(self.posting_date) if self.posting_date else getdate()
		if template.from_date and posting_date < getdate(template.from_date):
			frappe.throw(
				_("Journal Entry Template {0} is only valid from {1}.").format(
					link, formatdate(template.from_date)
				)
			)
		if template.end_date and posting_date > getdate(template.end_date):
			frappe.throw(
				_("Journal Entry Template {0} is only valid until {1}.").format(
					link, formatdate(template.end_date)
				)
			)

	def validate_against_template(self):
		# Structural validation runs whenever `from_template` is set — we
		# deliberately don't gate on `template_applied` here. The flag exists
		# as a UI hint (for the JS to know when to apply client-side locks),
		# but the server-side guarantee that "rows must match the template"
		# is rooted in the link itself, not the flag. Gating on the flag
		# created a bypass: tampering APIs could clear `template_applied`
		# and then freely mutate row structure, skipping this validator
		# entirely.
		if not self.from_template:
			return
		if not frappe.db.exists("Journal Entry Template", self.from_template):
			return

		template = frappe.get_cached_doc("Journal Entry Template", self.from_template)
		expected = sorted(
			(r.account, r.party_type or "") for r in template.accounts
		)
		actual_template_rows = sorted(
			(r.account, r.party_type or "") for r in self.accounts if r.from_template
		)
		if expected != actual_template_rows:
			frappe.throw(
				_(
					"Template-derived account rows do not match {0}. "
					"Clear and reapply the template, or remove the template reference."
				).format(get_link_to_form("Journal Entry Template", self.from_template))
			)

		if not template.allow_additional_accounts:
			extra = [r for r in self.accounts if not r.from_template]
			if extra:
				frappe.throw(
					_(
						"Template {0} does not allow additional accounts. Remove rows that are not part of the template."
					).format(self.from_template)
				)

		self.validate_template_row_locks(template)
		self.validate_template_header_locks(template)

	@staticmethod
	def _field_values_match(doc_a, doc_b, fieldname, meta):
		# Fieldtype-normalised equality so a form-POSTed string ("2026-05-13",
		# "0") compares equal to the DB-typed value (datetime.date, False).
		# Shared by the reversal locks and the template header locks.
		df = meta.get_field(fieldname)
		fieldtype = df.fieldtype if df else None
		a, b = doc_a.get(fieldname), doc_b.get(fieldname)
		if fieldtype == "Date":
			return (getdate(a) if a else None) == (getdate(b) if b else None)
		if fieldtype == "Datetime":
			from frappe.utils import get_datetime

			return (get_datetime(a) if a else None) == (get_datetime(b) if b else None)
		if fieldtype in ("Check", "Int"):
			from frappe.utils import cint

			return cint(a) == cint(b)
		if fieldtype in ("Float", "Currency", "Percent"):
			return flt(a) == flt(b)
		# Treat None and "" as equivalent for text-like fields.
		return (a or None) == (b or None)

	def validate_template_header_locks(self, template):
		# Server-side mirror of the client header locks (TEMPLATE_HEADER_LOCKS in
		# journal_entry.js). Only enforced when the global Accounts Settings switch
		# is on, matching the client — which makes these fields read-only only in
		# that mode. Without this, a bulk edit / API write could change header
		# fields the template fixed (proven for is_opening). Reuses the same
		# fieldtype-normalised comparison as the reversal locks.
		if not frappe.db.get_single_value("Accounts Settings", "enforce_template_field_locking"):
			return
		# `auto_reverse_date` is deliberately excluded — it is the one reversal
		# field the operator may adjust on the JE (mirrors the client, where
		# only the date stays editable when auto_reverse_on == "Specific Date").
		header_fields = (
			"voucher_type",
			"company",
			"multi_currency",
			"is_opening",
			"naming_series",
			"enable_auto_reversal",
			"auto_reverse_on",
			"reversal_exchange_rate_type",
			"reversal_tax_mode",
			"reversal_cost_center_mode",
			"auto_submit_reversal",
		)
		for field in header_fields:
			if not (self.meta.has_field(field) and template.meta.has_field(field)):
				continue
			if not self._field_values_match(self, template, field, self.meta):
				frappe.throw(
					_("Field {0} is set by Journal Entry Template {1} and cannot be changed.").format(
						frappe.bold(_(self.meta.get_label(field) or field)),
						get_link_to_form("Journal Entry Template", self.from_template),
					)
				)

	def validate_template_row_locks(self, template):
		# Defect WA-0001-04 #5 — server-side mirror of the client row locks:
		# fields the template populated on a row (account, party, party_type,
		# cost_center, project and every accounting dimension) cannot be changed
		# on the template-derived JE row. Only template-FILLED values are
		# enforced, so accounting-dimension defaults on fields the template left
		# blank are still permitted. The account+party_type multiset check above
		# already guarantees the two row sets have equal length; because account
		# is always non-empty it is enforced positionally here, which also
		# catches any reordering of the locked rows.
		locked_fields = self.get_template_locked_row_fields()
		je_template_rows = [r for r in self.accounts if r.from_template]
		row_meta = frappe.get_meta("Journal Entry Account")
		for tpl_row, je_row in zip(template.accounts, je_template_rows):
			for field in locked_fields:
				tpl_val = tpl_row.get(field)
				if tpl_val in (None, ""):
					continue
				if (je_row.get(field) or None) != (tpl_val or None):
					frappe.throw(
						_(
							"Row #{0}: {1} is set by Journal Entry Template {2} and cannot be changed."
						).format(
							je_row.idx,
							frappe.bold(_(row_meta.get_label(field) or field)),
							get_link_to_form("Journal Entry Template", self.from_template),
						)
					)

	@staticmethod
	def get_template_locked_row_fields():
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)

		candidates = ["account", "party_type", "party", "is_advance", "cost_center", "project"]
		candidates += get_accounting_dimensions() or []
		row_meta = frappe.get_meta("Journal Entry Account")
		seen, fields = set(), []
		for field in candidates:
			if field not in seen and row_meta.has_field(field):
				seen.add(field)
				fields.append(field)
		return fields

	def validate_advance_accounts(self):
		journal_accounts = set([x.account for x in self.accounts])
		advance_accounts = set()
		advance_accounts.add(
			frappe.get_cached_value("Company", self.company, "default_advance_received_account")
		)
		advance_accounts.add(frappe.get_cached_value("Company", self.company, "default_advance_paid_account"))
		if advance_accounts_used := journal_accounts & advance_accounts:
			frappe.msgprint(
				_(
					"Making Journal Entries against advance accounts: {0} is not recommended. These Journals won't be available for Reconciliation."
				).format(frappe.bold(comma_and(advance_accounts_used)))
			)

	def validate_for_repost(self):
		validate_docs_for_voucher_types(["Journal Entry"])
		validate_docs_for_deferred_accounting([self.name], [])

	def submit(self):
		if len(self.accounts) > 100 and not self.meta.queue_in_background:
			queue_submission(self, "_submit")
		else:
			return self._submit()

	def before_cancel(self):
		self.has_asset_adjustment_entry()
		self.validate_no_active_auto_reversal()
		# WP GA-0001-03 / GAP-004: block cancel if any PRE on this JE is still
		# active. JEs reconciled as the payment side of a PRE need to be
		# unreconciled (via reversal PRE) first.
		from erpnext.accounts.doctype.payment_reconciliation_entry.cancel_guards import (
			assert_no_active_pres,
		)
		assert_no_active_pres("Journal Entry", self.name)

	def validate_no_active_auto_reversal(self):
		# Symmetric with the manual-reversal guard in make_reverse_journal_entry:
		# don't allow cancelling a JE that still has an active scheduled
		# auto-reversal, otherwise the Auto Repeat would later fire and try to
		# reverse a cancelled entry. The user must disable/cancel the schedule
		# first. Capability-checked so it's safe before GA-0001-05+06 lands.
		if not frappe.get_meta("Auto Repeat").has_field("repeat_type"):
			return
		active_ar = frappe.db.get_value(
			"Auto Repeat",
			{
				"reference_doctype": "Journal Entry",
				"reference_document": self.name,
				"repeat_type": "Reversal",
				"status": "Active",
				"disabled": 0,
			},
			"name",
		)
		if active_ar:
			frappe.throw(
				_(
					"{0} has an active Auto Repeat reversal {1}. "
					"Disable or cancel the Auto Repeat before cancelling this Journal Entry."
				).format(
					frappe.bold(self.name),
					get_link_to_form("Auto Repeat", active_ar),
				)
			)

	def cancel(self):
		if len(self.accounts) > 100:
			queue_submission(self, "_cancel")
		else:
			return self._cancel()

	def before_submit(self):
		# Do not validate while importing via data import
		if not frappe.flags.in_import:
			self.validate_total_debit_and_credit()

	def on_submit(self):
		self.validate_cheque_info()
		self.make_gl_entries()
		self.check_credit_limit()
		self.update_asset_value()
		self.update_inter_company_jv()
		self.update_invoice_discounting()
		JournalTaxWithholding(self).on_submit()
		self.update_reversal_link()
		self._maybe_create_auto_reversal_repeat()

	def _maybe_create_auto_reversal_repeat(self):
		# WA-0001-05 #9 — auto-reversal is available on ANY Journal Entry whose
		# "Enable Auto Reversal" is set, whether or not it was created from a
		# template. Template-derived JEs inherit (and lock) the config; manual JEs
		# set it directly on the form.
		if not self.enable_auto_reversal:
			return
		if getattr(self, "is_reversal", 0):
			return
		if not frappe.get_meta("Auto Repeat").has_field("repeat_type"):
			frappe.log_error(
				title="Auto reversal skipped",
				message=(
					f"Journal Entry {self.name}: enable_auto_reversal=1 but the Auto Repeat doctype "
					f"does not have repeat_type (GA-0001-05+06 not deployed). "
					f"No reversal scheduled."
				),
			)
			return

		# Compute the schedule date and the AR-side reversal-config fields
		# from the JE's mirrored auto-reversal config. The handler now reads
		# the reversal config off the Auto Repeat (per imp_ga-0001-05+06.md
		# §"Schema additions" — AR is the canonical source), falling back
		# to the JE for back-compat with ARs created before this field set
		# was installed.
		from frappe.utils import add_months, get_first_day, getdate

		if self.auto_reverse_on == "Specific Date" and self.auto_reverse_date:
			start_date = getdate(self.auto_reverse_date)
			reverse_on_next_month = 0
			reverse_date = getdate(self.auto_reverse_date)
		else:
			start_date = get_first_day(add_months(getdate(), 1))
			reverse_on_next_month = 1
			reverse_date = None

		# Only populate the Reversal Options fields when they exist on the
		# Auto Repeat doctype. Pre-WP-05+06-tab deploys lack them; the
		# handler will fall back to reading from the JE in that case.
		ar_meta = frappe.get_meta("Auto Repeat")
		payload = {
			"reference_doctype": "Journal Entry",
			"reference_document": self.name,
			"repeat_type": "Reversal",
			# Keep submit_on_creation aligned with the JE's Auto Submit Reversal
			# config. In Reversal mode the handler controls submission via
			# auto_submit_reversal (submit_on_creation is not consumed on this
			# path), but they must agree so the stored config is not misleading.
			"submit_on_creation": self.auto_submit_reversal or 0,
			"start_date": start_date,
			# frappe's Auto Repeat requires `frequency` (reqd=1). For our
			# single-fire Reversal flow it's a placeholder — ERPNextAutoRepeat's
			# set_dates uses start_date directly for Reversal mode and never
			# consumes frequency. We pick "Daily" arbitrarily.
			"frequency": "Daily",
		}
		if ar_meta.has_field("reverse_on_next_month"):
			payload["reverse_on_next_month"] = reverse_on_next_month
			payload["reverse_date"] = reverse_date
			payload["auto_submit_reversal"] = self.auto_submit_reversal or 0
			payload["reversal_exchange_rate_type"] = self.reversal_exchange_rate_type or "Original Rate"
			payload["reversal_tax_mode"] = self.reversal_tax_mode or "Use Original"
			payload["reversal_cost_center_mode"] = self.reversal_cost_center_mode or "Use Original"

		ar = frappe.new_doc("Auto Repeat")
		ar.update(payload)
		ar.flags.ignore_permissions = True
		ar.insert()
		# Don't call ar.submit() — Auto Repeat is not a submittable doctype
		# per its doctype JSON. Calling submit() still sets docstatus=1,
		# which Frappe's UI treats as read-only-everywhere on the form
		# (locking the `disabled` checkbox and status Select so the user
		# can't cancel the schedule). The scheduler gates on
		# `status='Active' AND !disabled`, not docstatus, so submit() was
		# never functionally required — it only broke the UX.

		# Back-link the new AR onto this JE so the form indicator and any
		# JE-side reports can resolve "what's scheduled for this JE". The
		# manual-reversal guard in `make_reverse_journal_entry` scans Auto
		# Repeat directly (doesn't depend on this back-link) — this is for
		# visibility/audit, not enforcement.
		if self.meta.has_field("linked_auto_repeat"):
			self.db_set("linked_auto_repeat", ar.name, update_modified=False)
		if self.meta.has_field("auto_reversal_status"):
			self.db_set("auto_reversal_status", "Scheduled", update_modified=False)

	@frappe.whitelist()
	def get_balance_for_periodic_accounting(self):
		self.validate_company_for_periodic_accounting()

		stock_accounts = self.get_stock_accounts_for_periodic_accounting()
		self.set("accounts", [])
		for account in stock_accounts:
			account_bal, stock_bal, warehouse_list = get_stock_and_account_balance(
				account, self.posting_date, self.company
			)

			difference_value = flt(stock_bal - account_bal, self.precision("difference"))

			if difference_value == 0:
				frappe.msgprint(
					_("No difference found for stock account {0}").format(frappe.bold(account)),
					alert=True,
				)
				continue

			self.append(
				"accounts",
				{
					"account": account,
					"debit_in_account_currency": difference_value if difference_value > 0 else 0,
					"credit_in_account_currency": abs(difference_value) if difference_value < 0 else 0,
				},
			)

			self.append(
				"accounts",
				{
					"account": self.periodic_entry_difference_account,
					"credit_in_account_currency": difference_value if difference_value > 0 else 0,
					"debit_in_account_currency": abs(difference_value) if difference_value < 0 else 0,
				},
			)

	def validate_company_for_periodic_accounting(self):
		if erpnext.is_perpetual_inventory_enabled(self.company):
			frappe.throw(
				_(
					"Periodic Accounting Entry is not allowed for company {0} with perpetual inventory enabled"
				).format(self.company)
			)

		if not self.periodic_entry_difference_account:
			frappe.throw(_("Please select Periodic Accounting Entry Difference Account"))

	def get_stock_accounts_for_periodic_accounting(self):
		if self.voucher_type != "Periodic Accounting Entry":
			return []

		if self.for_all_stock_asset_accounts:
			return frappe.get_all(
				"Account",
				filters={
					"company": self.company,
					"account_type": "Stock",
					"root_type": "Asset",
					"is_group": 0,
				},
				pluck="name",
			)

		if not self.stock_asset_account:
			frappe.throw(_("Please select Stock Asset Account"))

		return [self.stock_asset_account]

	def on_update_after_submit(self):
		# Flag will be set on Reconciliation
		# Reconciliation tool will anyways repost ledger entries. So, no need to check and do implicit repost.
		if self.flags.get("ignore_reposting_on_reconciliation"):
			return

		self.needs_repost = self.check_if_fields_updated(fields_to_check=[], child_tables={"accounts": []})
		if self.needs_repost:
			self.validate_for_repost()
			self.repost_accounting_entries()

	def on_cancel(self):
		# Cancel tax withholding entries

		self.validate_reversal_cancel_allowed()

		# References for this Journal are removed on the `on_cancel` event in accounts_controller
		super().on_cancel()

		from_doc_events = getattr(self, "ignore_linked_doctypes", ())
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Stock Ledger Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
			"Advance Payment Ledger Entry",
			"Tax Withholding Entry",
		)

		if from_doc_events and from_doc_events != self.ignore_linked_doctypes:
			self.ignore_linked_doctypes = self.ignore_linked_doctypes + from_doc_events

		# WP GA-0001-03 / GAP-004: silence Frappe's generic PRE link check;
		# the active-only guard in `before_cancel` already enforced the rule.
		from erpnext.accounts.doctype.payment_reconciliation_entry.cancel_guards import (
			add_pre_to_ignore_linked_doctypes,
		)
		add_pre_to_ignore_linked_doctypes(self)

		self.make_gl_entries(1)
		JournalTaxWithholding(self).on_cancel()
		self.unlink_advance_entry_reference()
		self.unlink_asset_reference()
		self.unlink_inter_company_jv()
		self.unlink_asset_adjustment_entry()
		self.update_invoice_discounting()
		self.clear_reversal_link()

	def validate_reversal_cancel_allowed(self):
		if not self.is_reversal:
			return

		from erpnext.accounts.utils import is_immutable_ledger_enabled

		if is_immutable_ledger_enabled():
			frappe.throw(
				_(
					"Cannot cancel Reversal Journal Entry {0} while Immutable Ledger is enabled. Disable Immutable Ledger in Accounts Settings to allow cancelling reversal entries."
				).format(frappe.bold(self.name))
			)

	def validate_reversal_locked_fields(self):
		if not self.is_reversal or not self.reversal_of or self.docstatus == 2:
			return
		if self.is_new():
			# Fresh mapped draft — nothing to diff yet.
			return

		original = frappe.get_doc("Journal Entry", self.reversal_of)

		# WA-0001-01 #7 — is_opening is allow_on_submit, so without this it stays
		# editable on a submitted reversal; lock it to the original here.
		header_fields = ("company", "voucher_type", "multi_currency", "cheque_no", "cheque_date", "is_opening")
		for field in header_fields:
			if not self._field_values_match(self, original, field, self.meta):
				frappe.throw(
					_("Field {0} cannot be modified on a Reversal Journal Entry.").format(
						frappe.bold(_(self.meta.get_label(field) or field))
					)
				)

		if len(self.accounts) != len(original.accounts):
			frappe.throw(
				_("Rows cannot be added or removed on a Reversal Journal Entry.")
			)

		row_fields = (
			"account",
			"party_type",
			"party",
			"reference_type",
			"reference_name",
			"cost_center",
			"project",
			"account_currency",
		)
		# WA-0001-01 #7 — is_advance is deliberately NOT diffed against the
		# original. A reversal flips debit<->credit, so an advance row cannot
		# keep is_advance="Yes" (it would violate the advance direction rule),
		# and is never carried over (see make_reverse_journal_entry). The field
		# is still locked read-only on the form via lock_reversal_fields, which
		# satisfies the "not editable" requirement without an impossible diff.
		original_rows = {row.idx: row for row in original.accounts}
		row_meta = frappe.get_meta("Journal Entry Account")
		for reversal_row in self.accounts:
			original_row = original_rows.get(reversal_row.idx)
			if not original_row:
				continue
			for field in row_fields:
				if field == "cost_center" and not self.respect_cost_center_allocation:
					# cost_center is allowed to change when re-resolution is requested.
					continue
				if not self._field_values_match(reversal_row, original_row, field, row_meta):
					frappe.throw(
						_("Row #{0}: Field {1} cannot be modified on a Reversal Journal Entry.").format(
							reversal_row.idx,
							frappe.bold(_(reversal_row.meta.get_label(field) or field)),
						)
					)

			original_debit = flt(original_row.debit_in_account_currency)
			original_credit = flt(original_row.credit_in_account_currency)
			if (
				flt(reversal_row.debit_in_account_currency) != original_credit
				or flt(reversal_row.credit_in_account_currency) != original_debit
			):
				frappe.throw(
					_(
						"Row #{0}: Debit/Credit amounts on a Reversal Journal Entry must mirror the original entry."
					).format(reversal_row.idx)
				)

	def validate_reversal_totals_match_original(self):
		if not self.is_reversal or not self.reversal_of or self.docstatus == 2:
			return

		original = frappe.db.get_value(
			"Journal Entry",
			self.reversal_of,
			["total_debit", "total_credit"],
			as_dict=True,
		)
		if not original:
			return

		debit_precision = self.precision("total_debit")
		credit_precision = self.precision("total_credit")

		if flt(self.total_debit, debit_precision) != flt(original.total_credit, credit_precision):
			frappe.throw(
				_(
					"Reversal entry total debit ({0}) must match the original entry's total credit ({1})."
				).format(
					fmt_money(self.total_debit, precision=debit_precision),
					fmt_money(original.total_credit, precision=credit_precision),
				)
			)

		if flt(self.total_credit, credit_precision) != flt(original.total_debit, debit_precision):
			frappe.throw(
				_(
					"Reversal entry total credit ({0}) must match the original entry's total debit ({1})."
				).format(
					fmt_money(self.total_credit, precision=credit_precision),
					fmt_money(original.total_debit, precision=debit_precision),
				)
			)

	def maybe_reresolve_cost_center(self):
		if not self.is_reversal or self.respect_cost_center_allocation or self.docstatus == 2:
			return
		if not self.reversal_of:
			return

		original = frappe.get_doc("Journal Entry", self.reversal_of)
		original_rows = {row.idx: row for row in original.accounts}
		for row in self.accounts:
			original_row = original_rows.get(row.idx)
			if not original_row or not original_row.cost_center:
				continue
			# WP GA-0001-01: resolve the main cost center using the REVERSAL's
			# posting date (not the original's) so the cost-center allocation
			# active at the reversal date is the one re-applied on the post side.
			main_cost_center = _find_main_cost_center_for_leaf(
				original_row.cost_center, self.posting_date
			)
			if main_cost_center:
				row.cost_center = main_cost_center

	def update_reversal_link(self):
		if not self.is_reversal or not self.reversal_of:
			return
		frappe.db.set_value(
			"Journal Entry",
			self.reversal_of,
			{"reversed_by": self.name, "is_reversed": 1},
			update_modified=False,
		)

	def clear_reversal_link(self):
		if not self.is_reversal or not self.reversal_of:
			return
		frappe.db.set_value(
			"Journal Entry",
			self.reversal_of,
			{"reversed_by": None, "is_reversed": 0},
			update_modified=False,
		)

	def get_title(self):
		return self.pay_to_recd_from or self.accounts[0].account

	def validate_inter_company_accounts(self):
		if self.voucher_type == "Inter Company Journal Entry" and self.inter_company_journal_entry_reference:
			doc = frappe.db.get_value(
				"Journal Entry",
				self.inter_company_journal_entry_reference,
				["company", "total_debit", "total_credit"],
				as_dict=True,
			)
			account_currency = frappe.get_cached_value("Company", self.company, "default_currency")
			previous_account_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
			if account_currency == previous_account_currency:
				credit_precision = self.precision("total_credit")
				debit_precision = self.precision("total_debit")
				if (flt(self.total_credit, credit_precision) != flt(doc.total_debit, debit_precision)) or (
					flt(self.total_debit, debit_precision) != flt(doc.total_credit, credit_precision)
				):
					frappe.throw(_("Total Credit/ Debit Amount should be same as linked Journal Entry"))

	def validate_depr_account_and_depr_entry_voucher_type(self):
		for d in self.get("accounts"):
			if d.account_type == "Depreciation":
				if self.voucher_type != "Depreciation Entry":
					frappe.throw(
						_("Journal Entry type should be set as Depreciation Entry for asset depreciation")
					)

				if frappe.get_cached_value("Account", d.account, "root_type") != "Expense":
					frappe.throw(_("Account {0} should be of type Expense").format(d.account))

	def validate_stock_accounts(self):
		if (
			not erpnext.is_perpetual_inventory_enabled(self.company)
			or self.voucher_type == "Periodic Accounting Entry"
		):
			# Skip validation for periodic accounting entry and Perpetual Inventory Disabled Company.
			return

		stock_accounts = get_stock_accounts(self.company, accounts=self.accounts)
		for account in stock_accounts:
			account_bal, stock_bal, warehouse_list = get_stock_and_account_balance(
				account, self.posting_date, self.company
			)

			if account_bal == stock_bal:
				frappe.throw(
					_("Account: {0} can only be updated via Stock Transactions").format(account),
					StockAccountInvalidTransaction,
				)

	def update_asset_value(self):
		self.update_asset_on_depreciation()
		self.update_asset_on_disposal()

	def update_asset_on_depreciation(self):
		if self.voucher_type != "Depreciation Entry":
			return

		for d in self.get("accounts"):
			if (
				d.reference_type == "Asset"
				and d.reference_name
				and frappe.get_cached_value("Account", d.account, "root_type") == "Expense"
				and d.debit
			):
				asset = frappe.get_cached_doc("Asset", d.reference_name)

				if asset.calculate_depreciation:
					self.update_journal_entry_link_on_depr_schedule(asset, d)
					self.update_value_after_depreciation(asset, d.debit)

				asset.db_set("value_after_depreciation", asset.value_after_depreciation - d.debit)
				asset.set_status()
				asset.set_total_booked_depreciations()

	def update_value_after_depreciation(self, asset, depr_amount):
		fb_idx = 1
		if self.finance_book:
			for fb_row in asset.get("finance_books"):
				if fb_row.finance_book == self.finance_book:
					fb_idx = fb_row.idx
					break
		fb_row = asset.get("finance_books")[fb_idx - 1]
		fb_row.value_after_depreciation -= depr_amount
		frappe.db.set_value(
			"Asset Finance Book", fb_row.name, "value_after_depreciation", fb_row.value_after_depreciation
		)

	def update_journal_entry_link_on_depr_schedule(self, asset, je_row):
		depr_schedule = get_depr_schedule(asset.name, "Active", self.finance_book)
		for d in depr_schedule or []:
			if (
				d.schedule_date == self.posting_date
				and not d.journal_entry
				and d.depreciation_amount == flt(je_row.debit)
			):
				frappe.db.set_value("Depreciation Schedule", d.name, "journal_entry", self.name)

	def update_asset_on_disposal(self):
		if self.voucher_type == "Asset Disposal":
			disposed_assets = []
			for d in self.get("accounts"):
				if (
					d.reference_type == "Asset"
					and d.reference_name
					and d.reference_name not in disposed_assets
				):
					frappe.db.set_value(
						"Asset",
						d.reference_name,
						{
							"disposal_date": self.posting_date,
							"journal_entry_for_scrap": self.name,
						},
					)
					asset_doc = frappe.get_doc("Asset", d.reference_name)
					asset_doc.set_status()
					disposed_assets.append(d.reference_name)

	def update_inter_company_jv(self):
		if self.voucher_type == "Inter Company Journal Entry" and self.inter_company_journal_entry_reference:
			frappe.db.set_value(
				"Journal Entry",
				self.inter_company_journal_entry_reference,
				"inter_company_journal_entry_reference",
				self.name,
			)

	def update_invoice_discounting(self):
		def _validate_invoice_discounting_status(inv_disc, id_status, expected_status, row_id):
			id_link = get_link_to_form("Invoice Discounting", inv_disc)
			if id_status != expected_status:
				frappe.throw(
					_("Row #{0}: Status must be {1} for Invoice Discounting {2}").format(
						d.idx, expected_status, id_link
					)
				)

		invoice_discounting_list = list(
			set([d.reference_name for d in self.accounts if d.reference_type == "Invoice Discounting"])
		)
		for inv_disc in invoice_discounting_list:
			inv_disc_doc = frappe.get_doc("Invoice Discounting", inv_disc)
			status = None
			for d in self.accounts:
				if d.account == inv_disc_doc.short_term_loan and d.reference_name == inv_disc:
					if self.docstatus == 1:
						if d.credit > 0:
							_validate_invoice_discounting_status(
								inv_disc, inv_disc_doc.status, "Sanctioned", d.idx
							)
							status = "Disbursed"
						elif d.debit > 0:
							_validate_invoice_discounting_status(
								inv_disc, inv_disc_doc.status, "Disbursed", d.idx
							)
							status = "Settled"
					else:
						if d.credit > 0:
							_validate_invoice_discounting_status(
								inv_disc, inv_disc_doc.status, "Disbursed", d.idx
							)
							status = "Sanctioned"
						elif d.debit > 0:
							_validate_invoice_discounting_status(
								inv_disc, inv_disc_doc.status, "Settled", d.idx
							)
							status = "Disbursed"
					break
			if status:
				inv_disc_doc.set_status(status=status)

	def unlink_advance_entry_reference(self):
		for d in self.get("accounts"):
			if d.is_advance == "Yes" and d.reference_type in ("Sales Invoice", "Purchase Invoice"):
				doc = frappe.get_doc(d.reference_type, d.reference_name)
				doc.delink_advance_entries(self.name)
				d.reference_type = ""
				d.reference_name = ""
				d.db_update()

	def unlink_asset_reference(self):
		for d in self.get("accounts"):
			if (
				self.voucher_type == "Depreciation Entry"
				and d.reference_type == "Asset"
				and d.reference_name
				and frappe.get_cached_value("Account", d.account, "root_type") == "Expense"
				and d.debit
			):
				asset = frappe.get_doc("Asset", d.reference_name)

				if asset.calculate_depreciation:
					je_found = False

					for fb_row in asset.get("finance_books"):
						if je_found:
							break

						depr_schedule = get_depr_schedule(asset.name, "Active", fb_row.finance_book)

						for s in depr_schedule or []:
							if s.journal_entry == self.name:
								s.db_set("journal_entry", None)

								fb_row.value_after_depreciation += d.debit
								fb_row.db_update()

								je_found = True
								break
					if not je_found:
						fb_idx = 1
						if self.finance_book:
							for fb_row in asset.get("finance_books"):
								if fb_row.finance_book == self.finance_book:
									fb_idx = fb_row.idx
									break

						fb_row = asset.get("finance_books")[fb_idx - 1]
						fb_row.value_after_depreciation += d.debit
						fb_row.db_update()
				asset.db_set("value_after_depreciation", asset.value_after_depreciation + d.debit)
				asset.set_status()
				asset.set_total_booked_depreciations()
			elif self.voucher_type == "Journal Entry" and d.reference_type == "Asset" and d.reference_name:
				journal_entry_for_scrap = frappe.db.get_value(
					"Asset", d.reference_name, "journal_entry_for_scrap"
				)

				if journal_entry_for_scrap == self.name:
					frappe.throw(
						_("Journal Entry for Asset scrapping cannot be cancelled. Please restore the Asset.")
					)

	def unlink_inter_company_jv(self):
		if self.voucher_type == "Inter Company Journal Entry" and self.inter_company_journal_entry_reference:
			frappe.db.set_value(
				"Journal Entry",
				self.inter_company_journal_entry_reference,
				"inter_company_journal_entry_reference",
				"",
			)
			frappe.db.set_value("Journal Entry", self.name, "inter_company_journal_entry_reference", "")

	def has_asset_adjustment_entry(self):
		if self.flags.get("via_asset_value_adjustment"):
			return

		asset_value_adjustment = frappe.db.get_value(
			"Asset Value Adjustment", {"docstatus": 1, "journal_entry": self.name}, "name"
		)
		if asset_value_adjustment:
			frappe.throw(
				_(
					"Cannot cancel this document as it is linked with the submitted Asset Value Adjustment <b>{0}</b>. Please cancel the Asset Value Adjustment to continue."
				).format(frappe.utils.get_link_to_form("Asset Value Adjustment", asset_value_adjustment))
			)

	def unlink_asset_adjustment_entry(self):
		AssetValueAdjustment = frappe.qb.DocType("Asset Value Adjustment")
		(
			frappe.qb.update(AssetValueAdjustment)
			.set(AssetValueAdjustment.journal_entry, None)
			.where(AssetValueAdjustment.journal_entry == self.name)
		).run()

	def validate_party(self):
		for d in self.get("accounts"):
			account_type = frappe.get_cached_value("Account", d.account, "account_type")

			if account_type in ["Receivable", "Payable"]:
				if (
					not (d.party_type and d.party) and not self.party_not_required
				):  # skipping validation if party_not_required is passed via payroll entry
					frappe.throw(
						_(
							"Row {0}: Party Type and Party is required for Receivable / Payable account {1}"
						).format(d.idx, d.account)
					)
				elif (
					d.party_type
					and frappe.db.get_value("Party Type", d.party_type, "account_type") != account_type
					and d.party_type
					!= "Employee"  # making an excpetion for employee since they can be both payable and receivable
				):
					frappe.throw(
						_("Row {0}: Account {1} and Party Type {2} have different account types").format(
							d.idx, d.account, d.party_type
						)
					)

	def check_credit_limit(self):
		customers = list(
			set(
				d.party
				for d in self.get("accounts")
				if d.party_type == "Customer" and d.party and flt(d.debit) > 0
			)
		)
		if customers:
			from erpnext.selling.doctype.customer.customer import check_credit_limit

			customer_details = frappe._dict(
				frappe.db.get_all(
					"Customer Credit Limit",
					filters={
						"parent": ["in", customers],
						"parenttype": ["=", "Customer"],
						"company": ["=", self.company],
					},
					fields=["parent", "bypass_credit_limit_check"],
					as_list=True,
				)
			)

			for customer in customers:
				ignore_outstanding_sales_order = bool(customer_details.get(customer))
				check_credit_limit(customer, self.company, ignore_outstanding_sales_order)

	def validate_cheque_info(self):
		if self.voucher_type in ["Bank Entry"]:
			if not self.cheque_no or not self.cheque_date:
				msgprint(
					_("Reference No & Reference Date is required for {0}").format(self.voucher_type),
					raise_exception=1,
				)

		if self.cheque_date and not self.cheque_no:
			msgprint(_("Reference No is mandatory if you entered Reference Date"), raise_exception=1)

	def validate_entries_for_advance(self):
		for d in self.get("accounts"):
			if d.reference_type not in ("Sales Invoice", "Purchase Invoice", "Journal Entry"):
				if (d.party_type == "Customer" and flt(d.credit) > 0) or (
					d.party_type == "Supplier" and flt(d.debit) > 0
				):
					if d.is_advance == "No":
						msgprint(
							_(
								"Row {0}: Please check 'Is Advance' against Account {1} if this is an advance entry."
							).format(d.idx, d.account),
							alert=True,
						)
					elif d.reference_type in ("Sales Order", "Purchase Order") and d.is_advance != "Yes":
						frappe.throw(
							_(
								"Row {0}: Payment against Sales/Purchase Order should always be marked as advance"
							).format(d.idx)
						)

				if d.is_advance == "Yes":
					if d.party_type == "Customer" and flt(d.debit) > 0:
						frappe.throw(_("Row {0}: Advance against Customer must be credit").format(d.idx))
					elif d.party_type == "Supplier" and flt(d.credit) > 0:
						frappe.throw(_("Row {0}: Advance against Supplier must be debit").format(d.idx))

	def system_generated_gain_loss(self):
		return (
			self.voucher_type == "Exchange Gain Or Loss" and self.multi_currency and self.is_system_generated
		)

	def validate_against_jv(self):
		for d in self.get("accounts"):
			if d.reference_type == "Journal Entry":
				account_root_type = frappe.get_cached_value("Account", d.account, "root_type")
				if (
					account_root_type == "Asset"
					and flt(d.debit) > 0
					and not self.system_generated_gain_loss()
				):
					frappe.throw(
						_(
							"Row #{0}: For {1}, you can select reference document only if account gets credited"
						).format(d.idx, d.account)
					)
				elif (
					account_root_type == "Liability"
					and flt(d.credit) > 0
					and not self.system_generated_gain_loss()
				):
					frappe.throw(
						_(
							"Row #{0}: For {1}, you can select reference document only if account gets debited"
						).format(d.idx, d.account)
					)

				if d.reference_name == self.name:
					frappe.throw(_("You can not enter current voucher in 'Against Journal Entry' column"))

				against_entries = frappe.db.sql(
					"""select * from `tabJournal Entry Account`
					where account = %s and docstatus = 1 and parent = %s
					and (reference_type is null or reference_type in ('', 'Sales Order', 'Purchase Order'))
					""",
					(d.account, d.reference_name),
					as_dict=True,
				)

				if not against_entries:
					if self.voucher_type != "Exchange Gain Or Loss":
						frappe.throw(
							_(
								"Journal Entry {0} does not have account {1} or already matched against other voucher"
							).format(d.reference_name, d.account)
						)
				else:
					dr_or_cr = "debit" if flt(d.credit) > 0 else "credit"
					valid = False
					for jvd in against_entries:
						if flt(jvd[dr_or_cr]) > 0:
							valid = True
					if not valid and not self.system_generated_gain_loss():
						frappe.throw(
							_("Against Journal Entry {0} does not have any unmatched {1} entry").format(
								d.reference_name, dr_or_cr
							)
						)

	def validate_reference_doc(self):
		"""Validates reference document"""
		field_dict = {
			"Sales Invoice": ["Customer", "Debit To"],
			"Purchase Invoice": ["Supplier", "Credit To"],
			"Sales Order": ["Customer"],
			"Purchase Order": ["Supplier"],
		}

		self.reference_totals = {}
		self.reference_types = {}
		self.reference_accounts = {}

		for d in self.get("accounts"):
			if not d.reference_type:
				d.reference_name = None
			if not d.reference_name:
				d.reference_type = None
			if d.reference_type and d.reference_name and (d.reference_type in list(field_dict)):
				dr_or_cr = (
					"credit_in_account_currency"
					if d.reference_type in ("Sales Order", "Sales Invoice")
					else "debit_in_account_currency"
				)

				# check debit or credit type Sales / Purchase Order
				if d.reference_type == "Sales Order" and flt(d.debit) > 0:
					frappe.throw(
						_("Row {0}: Debit entry can not be linked with a {1}").format(d.idx, d.reference_type)
					)

				if d.reference_type == "Purchase Order" and flt(d.credit) > 0:
					frappe.throw(
						_("Row {0}: Credit entry can not be linked with a {1}").format(
							d.idx, d.reference_type
						)
					)

				# set totals
				if d.reference_name not in self.reference_totals:
					self.reference_totals[d.reference_name] = 0.0

				if self.voucher_type not in ("Deferred Revenue", "Deferred Expense"):
					self.reference_totals[d.reference_name] += flt(d.get(dr_or_cr))

				self.reference_types[d.reference_name] = d.reference_type
				self.reference_accounts[d.reference_name] = d.account

				against_voucher = frappe.db.get_value(
					d.reference_type, d.reference_name, [scrub(dt) for dt in field_dict.get(d.reference_type)]
				)

				if not against_voucher:
					frappe.throw(_("Row {0}: Invalid reference {1}").format(d.idx, d.reference_name))

				# check if party and account match
				if d.reference_type in ("Sales Invoice", "Purchase Invoice"):
					if (
						self.voucher_type in ("Deferred Revenue", "Deferred Expense")
						and d.reference_detail_no
					):
						debit_or_credit = "Debit" if d.debit else "Credit"
						party_account = get_deferred_booking_accounts(
							d.reference_type, d.reference_detail_no, debit_or_credit
						)
						against_voucher = ["", against_voucher[1]]
					else:
						if d.reference_type == "Sales Invoice":
							party_account = (
								get_party_account_based_on_invoice_discounting(d.reference_name)
								or against_voucher[1]
							)
						else:
							party_account = against_voucher[1]

					if (
						against_voucher[0] != cstr(d.party) or party_account != d.account
					) and self.voucher_type != "Exchange Gain Or Loss":
						frappe.throw(
							_("Row {0}: Party / Account does not match with {1} / {2} in {3} {4}").format(
								d.idx,
								field_dict.get(d.reference_type)[0],
								field_dict.get(d.reference_type)[1],
								d.reference_type,
								d.reference_name,
							)
						)

				# check if party matches for Sales / Purchase Order
				if d.reference_type in ("Sales Order", "Purchase Order"):
					# set totals
					if against_voucher != d.party:
						frappe.throw(
							_("Row {0}: {1} {2} does not match with {3}").format(
								d.idx, d.party_type, d.party, d.reference_type
							)
						)

		self.validate_orders()
		self.validate_invoices()

	def validate_orders(self):
		"""Validate totals, closed and docstatus for orders"""
		for reference_name, total in self.reference_totals.items():
			reference_type = self.reference_types[reference_name]
			account = self.reference_accounts[reference_name]

			if reference_type in ("Sales Order", "Purchase Order"):
				order = frappe.get_doc(reference_type, reference_name)

				if order.docstatus != 1:
					frappe.throw(_("{0} {1} is not submitted").format(reference_type, reference_name))

				if flt(order.per_billed) >= 100:
					frappe.throw(_("{0} {1} is fully billed").format(reference_type, reference_name))

				if cstr(order.status) == "Closed":
					frappe.throw(_("{0} {1} is closed").format(reference_type, reference_name))

				account_currency = get_account_currency(account)
				if account_currency == self.company_currency:
					voucher_total = order.base_grand_total
					formatted_voucher_total = fmt_money(
						voucher_total, order.precision("base_grand_total"), currency=account_currency
					)
				else:
					voucher_total = order.grand_total
					formatted_voucher_total = fmt_money(
						voucher_total, order.precision("grand_total"), currency=account_currency
					)

				if flt(voucher_total) < (flt(order.advance_paid) + total):
					frappe.throw(
						_("Advance paid against {0} {1} cannot be greater than Grand Total {2}").format(
							reference_type, reference_name, formatted_voucher_total
						)
					)

	def validate_invoices(self):
		"""Validate totals and docstatus for invoices"""
		for reference_name, total in self.reference_totals.items():
			reference_type = self.reference_types[reference_name]

			if reference_type in ("Sales Invoice", "Purchase Invoice") and self.voucher_type not in [
				"Debit Note",
				"Credit Note",
			]:
				invoice = frappe.get_doc(reference_type, reference_name)

				if invoice.docstatus != 1:
					frappe.throw(_("{0} {1} is not submitted").format(reference_type, reference_name))

				precision = invoice.precision("outstanding_amount")
				if total and flt(invoice.outstanding_amount, precision) < flt(total, precision):
					frappe.throw(
						_("Payment against {0} {1} cannot be greater than Outstanding Amount {2}").format(
							reference_type, reference_name, invoice.outstanding_amount
						)
					)

	def set_against_account(self):
		accounts_debited, accounts_credited = [], []
		if self.voucher_type in ("Deferred Revenue", "Deferred Expense"):
			for d in self.get("accounts"):
				if d.reference_type == "Sales Invoice":
					field = "customer"
				else:
					field = "supplier"

				d.against_account = frappe.db.get_value(d.reference_type, d.reference_name, field)
		else:
			for d in self.get("accounts"):
				if flt(d.debit) > 0:
					accounts_debited.append(d.party or d.account)
				if flt(d.credit) > 0:
					accounts_credited.append(d.party or d.account)

			for d in self.get("accounts"):
				if flt(d.debit) > 0:
					d.against_account = ", ".join(list(set(accounts_credited)))
				if flt(d.credit) > 0:
					d.against_account = ", ".join(list(set(accounts_debited)))

	def validate_debit_credit_amount(self):
		if not (self.voucher_type == "Exchange Gain Or Loss" and self.multi_currency):
			for d in self.get("accounts"):
				if not flt(d.debit) and not flt(d.credit):
					frappe.throw(_("Row {0}: Both Debit and Credit values cannot be zero").format(d.idx))

	def validate_total_debit_and_credit(self):
		if not (self.voucher_type == "Exchange Gain Or Loss" and self.multi_currency):
			if self.difference:
				frappe.throw(
					_("Total Debit must be equal to Total Credit. The difference is {0}").format(
						self.difference
					)
				)

	def set_total_debit_credit(self):
		self.total_debit, self.total_credit, self.difference = 0, 0, 0
		for d in self.get("accounts"):
			if d.debit and d.credit:
				frappe.throw(_("You cannot credit and debit same account at the same time"))

			self.total_debit = flt(self.total_debit) + flt(d.debit, d.precision("debit"))
			self.total_credit = flt(self.total_credit) + flt(d.credit, d.precision("credit"))

		self.difference = flt(self.total_debit, self.precision("total_debit")) - flt(
			self.total_credit, self.precision("total_credit")
		)

	def validate_multi_currency(self):
		alternate_currency = []
		for d in self.get("accounts"):
			account = frappe.get_cached_value(
				"Account", d.account, ["account_currency", "account_type"], as_dict=1
			)
			if account:
				d.account_currency = account.account_currency
				d.account_type = account.account_type

			if not d.account_currency:
				d.account_currency = self.company_currency

			if d.account_currency != self.company_currency and d.account_currency not in alternate_currency:
				alternate_currency.append(d.account_currency)

		if alternate_currency:
			if not self.multi_currency:
				frappe.throw(_("Please check Multi Currency option to allow accounts with other currency"))

		self.set_exchange_rate()

	def set_amounts_in_company_currency(self):
		if not (self.voucher_type == "Exchange Gain Or Loss" and self.multi_currency):
			for d in self.get("accounts"):
				d.debit_in_account_currency = flt(
					d.debit_in_account_currency, d.precision("debit_in_account_currency")
				)
				d.credit_in_account_currency = flt(
					d.credit_in_account_currency, d.precision("credit_in_account_currency")
				)

				d.debit = flt(d.debit_in_account_currency * flt(d.exchange_rate), d.precision("debit"))
				d.credit = flt(d.credit_in_account_currency * flt(d.exchange_rate), d.precision("credit"))

	def set_exchange_rate(self):
		for d in self.get("accounts"):
			if d.account_currency == self.company_currency:
				d.exchange_rate = 1
			elif (
				not d.exchange_rate
				or d.exchange_rate == 1
				or (
					d.reference_type in ("Sales Invoice", "Purchase Invoice")
					and d.reference_name
					and self.posting_date
				)
			):
				ignore_exchange_rate = False
				if self.get("flags") and self.flags.get("ignore_exchange_rate"):
					ignore_exchange_rate = True

				if not ignore_exchange_rate:
					# Modified to include the posting date for which to retreive the exchange rate
					d.exchange_rate = get_exchange_rate(
						self.posting_date,
						d.account,
						d.account_currency,
						self.company,
						d.reference_type,
						d.reference_name,
						d.debit,
						d.credit,
						d.exchange_rate,
					)

			if not d.exchange_rate:
				frappe.throw(_("Row {0}: Exchange Rate is mandatory").format(d.idx))

	def create_remarks(self):
		r = []

		if self.flags.skip_remarks_creation:
			return

		if self.get("custom_remark"):
			return

		if self.cheque_no:
			if self.cheque_date:
				r.append(_("Reference #{0} dated {1}").format(self.cheque_no, formatdate(self.cheque_date)))
			else:
				msgprint(_("Please enter Reference date"), raise_exception=frappe.MandatoryError)

		for d in self.get("accounts"):
			if d.reference_type == "Sales Invoice" and d.credit:
				r.append(
					_("{0} against Sales Invoice {1}").format(
						fmt_money(flt(d.credit), currency=self.company_currency), d.reference_name
					)
				)

			if d.reference_type == "Sales Order" and d.credit:
				r.append(
					_("{0} against Sales Order {1}").format(
						fmt_money(flt(d.credit), currency=self.company_currency), d.reference_name
					)
				)

			if d.reference_type == "Purchase Invoice" and d.debit:
				bill_no = frappe.db.sql(
					"""select bill_no, bill_date
					from `tabPurchase Invoice` where name=%s""",
					d.reference_name,
				)
				if (
					bill_no
					and bill_no[0][0]
					and bill_no[0][0].lower().strip() not in ["na", "not applicable", "none"]
				):
					r.append(
						_("{0} against Bill {1} dated {2}").format(
							fmt_money(flt(d.debit), currency=self.company_currency),
							bill_no[0][0],
							bill_no[0][1] and formatdate(bill_no[0][1].strftime("%Y-%m-%d")),
						)
					)

			if d.reference_type == "Purchase Order" and d.debit:
				r.append(
					_("{0} against Purchase Order {1}").format(
						fmt_money(flt(d.credit), currency=self.company_currency), d.reference_name
					)
				)

		if r:
			self.remark = ("\n").join(r)  # User Remarks is not mandatory

	def set_print_format_fields(self):
		bank_amount = party_amount = total_amount = 0.0
		currency = bank_account_currency = party_account_currency = pay_to_recd_from = None
		party_type = None
		for d in self.get("accounts"):
			if d.party_type in ["Customer", "Supplier"] and d.party:
				party_type = d.party_type
				if not pay_to_recd_from:
					pay_to_recd_from = d.party

				if pay_to_recd_from and pay_to_recd_from == d.party:
					party_amount += flt(d.debit_in_account_currency) or flt(d.credit_in_account_currency)
					party_account_currency = d.account_currency

			elif frappe.get_cached_value("Account", d.account, "account_type") in ["Bank", "Cash"]:
				bank_amount += flt(d.debit_in_account_currency) or flt(d.credit_in_account_currency)
				bank_account_currency = d.account_currency

		if party_type and pay_to_recd_from:
			self.pay_to_recd_from = frappe.db.get_value(
				party_type, pay_to_recd_from, "customer_name" if party_type == "Customer" else "supplier_name"
			)
			if bank_amount:
				total_amount = bank_amount
				currency = bank_account_currency
			else:
				total_amount = party_amount
				currency = party_account_currency

		self.set_total_amount(total_amount, currency)

	def set_total_amount(self, amt, currency):
		self.total_amount = amt
		self.total_amount_currency = currency
		from frappe.utils import money_in_words

		self.total_amount_in_words = money_in_words(amt, currency)

	def build_gl_map(self):
		gl_map = []

		company_currency = erpnext.get_company_currency(self.company)
		self.transaction_currency = company_currency
		self.transaction_exchange_rate = 1
		if self.multi_currency:
			for row in self.get("accounts"):
				if row.account_currency != company_currency:
					# Journal assumes the first foreign currency as transaction currency
					self.transaction_currency = row.account_currency
					self.transaction_exchange_rate = row.exchange_rate
					break

		advance_doctypes = get_advance_payment_doctypes()

		for d in self.get("accounts"):
			if d.debit or d.credit or (self.voucher_type == "Exchange Gain Or Loss"):
				r = [d.user_remark, self.remark]
				r = [x for x in r if x]
				remarks = "\n".join(r)

				row = {
					"account": d.account,
					"party_type": d.party_type,
					"due_date": self.due_date,
					"party": d.party,
					"against": d.against_account,
					"debit": flt(d.debit, d.precision("debit")),
					"credit": flt(d.credit, d.precision("credit")),
					"account_currency": d.account_currency,
					"debit_in_account_currency": flt(
						d.debit_in_account_currency, d.precision("debit_in_account_currency")
					),
					"credit_in_account_currency": flt(
						d.credit_in_account_currency, d.precision("credit_in_account_currency")
					),
					"transaction_currency": self.transaction_currency,
					"transaction_exchange_rate": self.transaction_exchange_rate,
					"debit_in_transaction_currency": flt(
						d.debit_in_account_currency, d.precision("debit_in_account_currency")
					)
					if self.transaction_currency == d.account_currency
					else flt(d.debit, d.precision("debit")) / self.transaction_exchange_rate,
					"credit_in_transaction_currency": flt(
						d.credit_in_account_currency, d.precision("credit_in_account_currency")
					)
					if self.transaction_currency == d.account_currency
					else flt(d.credit, d.precision("credit")) / self.transaction_exchange_rate,
					"against_voucher_type": d.reference_type,
					"against_voucher": d.reference_name,
					"remarks": remarks,
					"voucher_detail_no": d.reference_detail_no,
					"cost_center": d.cost_center,
					"project": d.project,
					"finance_book": self.finance_book,
					"advance_voucher_type": d.advance_voucher_type,
					"advance_voucher_no": d.advance_voucher_no,
				}

				if d.reference_type in advance_doctypes:
					row.update(
						{
							"against_voucher_type": self.doctype,
							"against_voucher": self.name,
							"advance_voucher_type": d.reference_type,
							"advance_voucher_no": d.reference_name,
						}
					)

				# set flag to skip party validation
				account_type = frappe.get_cached_value("Account", d.account, "account_type")
				if account_type in ["Receivable", "Payable"] and self.party_not_required:
					frappe.flags.party_not_required = True

				gl_map.append(
					self.get_gl_dict(
						row,
						item=d,
					)
				)
		return gl_map

	def make_gl_entries(self, cancel=0, adv_adj=0):
		from erpnext.accounts.general_ledger import make_gl_entries

		merge_entries = frappe.get_single_value("Accounts Settings", "merge_similar_account_heads")

		gl_map = self.build_gl_map()
		if self.voucher_type in ("Deferred Revenue", "Deferred Expense"):
			update_outstanding = "No"
		else:
			update_outstanding = "Yes"

		if gl_map:
			make_gl_entries(
				gl_map,
				cancel=cancel,
				adv_adj=adv_adj,
				merge_entries=merge_entries,
				update_outstanding=update_outstanding,
			)
			frappe.flags.party_not_required = False
			if cancel:
				cancel_exchange_gain_loss_journal(frappe._dict(doctype=self.doctype, name=self.name))

	@frappe.whitelist()
	def get_balance(self, difference_account=None):
		if not self.get("accounts"):
			msgprint(_("'Entries' cannot be empty"), raise_exception=True)
		else:
			self.total_debit, self.total_credit = 0, 0
			diff = flt(self.difference, self.precision("difference"))

			# If any row without amount, set the diff on that row
			if diff:
				blank_row = None
				for d in self.get("accounts"):
					if not d.credit_in_account_currency and not d.debit_in_account_currency and diff != 0:
						blank_row = d

				if not blank_row:
					blank_row = self.append(
						"accounts",
						{
							"account": difference_account,
							"cost_center": erpnext.get_default_cost_center(self.company),
						},
					)

				blank_row.exchange_rate = 1
				if diff > 0:
					blank_row.credit_in_account_currency = diff
					blank_row.credit = diff
				elif diff < 0:
					blank_row.debit_in_account_currency = abs(diff)
					blank_row.debit = abs(diff)

			self.set_total_debit_credit()
			self.validate_total_debit_and_credit()

	@frappe.whitelist()
	def get_outstanding_invoices(self):
		self.set("accounts", [])
		total = 0
		for d in self.get_values():
			total += flt(d.outstanding_amount, self.precision("credit", "accounts"))
			jd1 = self.append("accounts", {})
			jd1.account = d.account
			jd1.party = d.party

			if self.write_off_based_on == "Accounts Receivable":
				jd1.party_type = "Customer"
				jd1.credit_in_account_currency = flt(
					d.outstanding_amount, self.precision("credit", "accounts")
				)
				jd1.reference_type = "Sales Invoice"
				jd1.reference_name = cstr(d.name)
			elif self.write_off_based_on == "Accounts Payable":
				jd1.party_type = "Supplier"
				jd1.debit_in_account_currency = flt(d.outstanding_amount, self.precision("debit", "accounts"))
				jd1.reference_type = "Purchase Invoice"
				jd1.reference_name = cstr(d.name)

		jd2 = self.append("accounts", {})
		if self.write_off_based_on == "Accounts Receivable":
			jd2.debit_in_account_currency = total
		elif self.write_off_based_on == "Accounts Payable":
			jd2.credit_in_account_currency = total

		self.validate_total_debit_and_credit()

	def get_values(self):
		cond = f" and outstanding_amount <= {self.write_off_amount}" if flt(self.write_off_amount) > 0 else ""

		if self.write_off_based_on == "Accounts Receivable":
			return frappe.db.sql(
				"""select name, debit_to as account, customer as party, outstanding_amount
				from `tabSales Invoice` where docstatus = 1 and company = {}
				and outstanding_amount > 0 {}""".format("%s", cond),
				self.company,
				as_dict=True,
			)
		elif self.write_off_based_on == "Accounts Payable":
			return frappe.db.sql(
				"""select name, credit_to as account, supplier as party, outstanding_amount
				from `tabPurchase Invoice` where docstatus = 1 and company = {}
				and outstanding_amount > 0 {}""".format("%s", cond),
				self.company,
				as_dict=True,
			)

	def validate_credit_debit_note(self):
		if self.stock_entry:
			if frappe.db.get_value("Stock Entry", self.stock_entry, "docstatus") != 1:
				frappe.throw(_("Stock Entry {0} is not submitted").format(self.stock_entry))

			if frappe.db.exists(
				{"doctype": "Journal Entry", "stock_entry": self.stock_entry, "docstatus": 1}
			):
				frappe.msgprint(
					_("Warning: Another {0} # {1} exists against stock entry {2}").format(
						self.voucher_type, self.name, self.stock_entry
					)
				)

	def validate_empty_accounts_table(self):
		if not self.get("accounts"):
			frappe.throw(_("Accounts table cannot be blank."))


@frappe.whitelist()
def get_default_bank_cash_account(
	company, account_type=None, mode_of_payment=None, account=None, *, fetch_balance=True
):
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

	if mode_of_payment:
		account = get_bank_cash_account(mode_of_payment, company).get("account")

	if not account:
		"""
		Set the default account first. If the user hasn't set any default account then, he doesn't
		want us to set any random account. In this case set the account only if there is single
		account (of that type), otherwise return empty dict.
		"""
		if account_type == "Bank":
			account = frappe.get_cached_value("Company", company, "default_bank_account")
			if not account:
				account_list = frappe.get_all(
					"Account", filters={"company": company, "account_type": "Bank", "is_group": 0}
				)
				if len(account_list) == 1:
					account = account_list[0].name

		elif account_type == "Cash":
			account = frappe.get_cached_value("Company", company, "default_cash_account")
			if not account:
				account_list = frappe.get_all(
					"Account", filters={"company": company, "account_type": "Cash", "is_group": 0}
				)
				if len(account_list) == 1:
					account = account_list[0].name

	if account:
		account_details = frappe.get_cached_value(
			"Account", account, ["account_currency", "account_type"], as_dict=1
		)
		result = {
			"account": account,
			"account_currency": account_details.account_currency,
			"account_type": account_details.account_type,
		}
		if fetch_balance:
			result["balance"] = get_balance_on(account)
		return frappe._dict(result)
	else:
		return frappe._dict()


@frappe.whitelist()
def get_payment_entry_against_order(
	dt, dn, amount=None, debit_in_account_currency=None, journal_entry=False, bank_account=None
):
	ref_doc = frappe.get_doc(dt, dn)

	if flt(ref_doc.per_billed, 2) > 0:
		frappe.throw(_("Can only make payment against unbilled {0}").format(dt))

	if dt == "Sales Order":
		party_type = "Customer"
		amount_field_party = "credit_in_account_currency"
		amount_field_bank = "debit_in_account_currency"
	else:
		party_type = "Supplier"
		amount_field_party = "debit_in_account_currency"
		amount_field_bank = "credit_in_account_currency"

	party_account = get_party_account(party_type, ref_doc.get(party_type.lower()), ref_doc.company)
	party_account_currency = get_account_currency(party_account)

	if not amount:
		if party_account_currency == ref_doc.company_currency:
			amount = flt(ref_doc.base_grand_total) - flt(ref_doc.advance_paid)
		else:
			amount = flt(ref_doc.grand_total) - flt(ref_doc.advance_paid)

	return get_payment_entry(
		ref_doc,
		{
			"party_type": party_type,
			"party_account": party_account,
			"party_account_currency": party_account_currency,
			"amount_field_party": amount_field_party,
			"amount_field_bank": amount_field_bank,
			"amount": amount,
			"debit_in_account_currency": debit_in_account_currency,
			"remarks": f"Advance Payment received against {dt} {dn}",
			"is_advance": "Yes",
			"bank_account": bank_account,
			"journal_entry": journal_entry,
		},
	)


@frappe.whitelist()
def get_payment_entry_against_invoice(
	dt, dn, amount=None, debit_in_account_currency=None, journal_entry=False, bank_account=None
):
	ref_doc = frappe.get_doc(dt, dn)
	if dt == "Sales Invoice":
		party_type = "Customer"
		party_account = get_party_account_based_on_invoice_discounting(dn) or ref_doc.debit_to
	else:
		party_type = "Supplier"
		party_account = ref_doc.credit_to

	if (dt == "Sales Invoice" and ref_doc.outstanding_amount > 0) or (
		dt == "Purchase Invoice" and ref_doc.outstanding_amount < 0
	):
		amount_field_party = "credit_in_account_currency"
		amount_field_bank = "debit_in_account_currency"
	else:
		amount_field_party = "debit_in_account_currency"
		amount_field_bank = "credit_in_account_currency"

	return get_payment_entry(
		ref_doc,
		{
			"party_type": party_type,
			"party_account": party_account,
			"party_account_currency": ref_doc.party_account_currency,
			"amount_field_party": amount_field_party,
			"amount_field_bank": amount_field_bank,
			"amount": amount if amount else abs(ref_doc.outstanding_amount),
			"debit_in_account_currency": debit_in_account_currency,
			"remarks": f"Payment received against {dt} {dn}. {ref_doc.remarks}",
			"is_advance": "No",
			"bank_account": bank_account,
			"journal_entry": journal_entry,
		},
	)


def get_payment_entry(ref_doc, args):
	cost_center = ref_doc.get("cost_center") or frappe.get_cached_value(
		"Company", ref_doc.company, "cost_center"
	)
	exchange_rate = 1
	if args.get("party_account"):
		# Modified to include the posting date for which the exchange rate is required.
		# Assumed to be the posting date in the reference document
		exchange_rate = get_exchange_rate(
			ref_doc.get("posting_date") or ref_doc.get("transaction_date"),
			args.get("party_account"),
			args.get("party_account_currency"),
			ref_doc.company,
			ref_doc.doctype,
			ref_doc.name,
		)

	je = frappe.new_doc("Journal Entry")
	je.update({"voucher_type": "Bank Entry", "company": ref_doc.company, "remark": args.get("remarks")})

	party_row = je.append(
		"accounts",
		{
			"account": args.get("party_account"),
			"party_type": args.get("party_type"),
			"party": ref_doc.get(args.get("party_type").lower()),
			"cost_center": cost_center,
			"account_type": frappe.get_cached_value("Account", args.get("party_account"), "account_type"),
			"account_currency": args.get("party_account_currency")
			or get_account_currency(args.get("party_account")),
			"exchange_rate": exchange_rate,
			args.get("amount_field_party"): args.get("amount"),
			"is_advance": args.get("is_advance"),
			"reference_type": ref_doc.doctype,
			"reference_name": ref_doc.name,
		},
	)

	bank_row = je.append("accounts")

	# Make it bank_details
	bank_account = get_default_bank_cash_account(ref_doc.company, "Bank", account=args.get("bank_account"))
	if bank_account:
		bank_row.update(bank_account)
		# Modified to include the posting date for which the exchange rate is required.
		# Assumed to be the posting date of the reference date
		bank_row.exchange_rate = get_exchange_rate(
			ref_doc.get("posting_date") or ref_doc.get("transaction_date"),
			bank_account["account"],
			bank_account["account_currency"],
			ref_doc.company,
		)

	bank_row.cost_center = cost_center

	amount = args.get("debit_in_account_currency") or args.get("amount")

	if bank_row.account_currency == args.get("party_account_currency"):
		bank_row.set(args.get("amount_field_bank"), amount)
	else:
		bank_row.set(args.get("amount_field_bank"), amount * exchange_rate)

	# Multi currency check again
	if party_row.account_currency != ref_doc.company_currency or (
		bank_row.account_currency and bank_row.account_currency != ref_doc.company_currency
	):
		je.multi_currency = 1

	je.set_amounts_in_company_currency()
	je.set_total_debit_credit()

	return je if args.get("journal_entry") else je.as_dict()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_against_jv(doctype, txt, searchfield, start, page_len, filters):
	if not frappe.db.has_column("Journal Entry", searchfield):
		return []

	JournalEntry = frappe.qb.DocType("Journal Entry")
	JournalEntryAccount = frappe.qb.DocType("Journal Entry Account")

	query = (
		frappe.qb.from_(JournalEntry)
		.join(JournalEntryAccount)
		.on(JournalEntryAccount.parent == JournalEntry.name)
		.select(JournalEntry.name, JournalEntry.posting_date, JournalEntry.remark)
		.where(JournalEntryAccount.account == filters.get("account"))
		.where(JournalEntryAccount.reference_type.isnull() | (JournalEntryAccount.reference_type == ""))
		.where(JournalEntry.docstatus == 1)
		.where(JournalEntry[searchfield].like(f"%{txt}%"))
		.orderby(JournalEntry.name, order=frappe.qb.desc)
		.limit(page_len)
		.offset(start)
	)

	party = filters.get("party")
	if party:
		query = query.where(JournalEntryAccount.party == party)
	else:
		query = query.where(JournalEntryAccount.party.isnull() | (JournalEntryAccount.party == ""))

	return query.run()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_available_templates(doctype, txt, searchfield, start, page_len, filters):
	# Defect WA-0001-04 #2 — the from_template picker previously listed every
	# non-disabled template; the from_date/end_date availability window was only
	# enforced server-side on save, so out-of-window templates still appeared in
	# the dropdown. Mirror that window here, treating null bounds as open-ended,
	# so the posting date filters the list directly.
	if not frappe.db.has_column("Journal Entry Template", searchfield):
		searchfield = "name"

	posting_date = (filters or {}).get("posting_date") or nowdate()

	Template = frappe.qb.DocType("Journal Entry Template")
	query = (
		frappe.qb.from_(Template)
		.select(Template.name)
		.where(Template.disabled == 0)
		.where(Template.from_date.isnull() | (Template.from_date <= posting_date))
		.where(Template.end_date.isnull() | (Template.end_date >= posting_date))
		.where(Template[searchfield].like(f"%{txt}%"))
		.orderby(Template.name)
		.limit(page_len)
		.offset(start)
	)
	return query.run()


@frappe.whitelist()
def get_outstanding(args):
	if not frappe.has_permission("Account"):
		frappe.msgprint(_("No Permission"), raise_exception=1)

	if isinstance(args, str):
		args = json.loads(args)

	company_currency = erpnext.get_company_currency(args.get("company"))
	due_date = None

	if args.get("doctype") == "Journal Entry":
		condition = " and party=%(party)s" if args.get("party") else ""

		against_jv_amount = frappe.db.sql(
			f"""
			select sum(debit_in_account_currency) - sum(credit_in_account_currency)
			from `tabJournal Entry Account` where parent=%(docname)s and account=%(account)s {condition}
			and (reference_type is null or reference_type = '')""",
			args,
		)

		against_jv_amount = flt(against_jv_amount[0][0]) if against_jv_amount else 0
		amount_field = "credit_in_account_currency" if against_jv_amount > 0 else "debit_in_account_currency"
		return {amount_field: abs(against_jv_amount)}
	elif args.get("doctype") in ("Sales Invoice", "Purchase Invoice"):
		party_type = "Customer" if args.get("doctype") == "Sales Invoice" else "Supplier"
		invoice = frappe.db.get_value(
			args["doctype"],
			args["docname"],
			["outstanding_amount", "conversion_rate", scrub(party_type), "due_date"],
			as_dict=1,
		)

		due_date = invoice.get("due_date")

		exchange_rate = invoice.conversion_rate if (args.get("account_currency") != company_currency) else 1

		if args["doctype"] == "Sales Invoice":
			amount_field = (
				"credit_in_account_currency"
				if flt(invoice.outstanding_amount) > 0
				else "debit_in_account_currency"
			)
		else:
			amount_field = (
				"debit_in_account_currency"
				if flt(invoice.outstanding_amount) > 0
				else "credit_in_account_currency"
			)

		return {
			amount_field: abs(flt(invoice.outstanding_amount)),
			"exchange_rate": exchange_rate,
			"party_type": party_type,
			"party": invoice.get(scrub(party_type)),
			"reference_due_date": due_date,
		}


@frappe.whitelist()
def get_party_account_and_currency(company, party_type, party):
	if not frappe.has_permission("Account"):
		frappe.msgprint(_("No Permission"), raise_exception=1)

	account = get_party_account(party_type, party, company)

	return {
		"account": account,
		"account_currency": frappe.get_cached_value("Account", account, "account_currency"),
	}


@frappe.whitelist()
def get_account_details_and_party_type(account, date, company, debit=None, credit=None, exchange_rate=None):
	"""Returns dict of account details and party type to be set in Journal Entry on selection of account."""
	if not frappe.has_permission("Account"):
		frappe.msgprint(_("No Permission"), raise_exception=1)

	company_currency = erpnext.get_company_currency(company)
	account_details = frappe.get_cached_value(
		"Account", account, ["account_type", "account_currency"], as_dict=1
	)

	if not account_details:
		return

	if account_details.account_type == "Receivable":
		party_type = "Customer"
	elif account_details.account_type == "Payable":
		party_type = "Supplier"
	else:
		party_type = ""

	grid_values = {
		"party_type": party_type,
		"account_type": account_details.account_type,
		"account_currency": account_details.account_currency or company_currency,
		"bank_account": (
			frappe.db.get_value("Bank Account", {"account": account, "company": company}) or None
		),
		# The date used to retreive the exchange rate here is the date passed in
		# as an argument to this function. It is assumed to be the date on which the balance is sought
		"exchange_rate": get_exchange_rate(
			date,
			account,
			account_details.account_currency,
			company,
			debit=debit,
			credit=credit,
			exchange_rate=exchange_rate,
		),
	}

	# un-set party if not party type
	if not party_type:
		grid_values["party"] = ""

	return grid_values


@frappe.whitelist()
def get_exchange_rate(
	posting_date,
	account=None,
	account_currency=None,
	company=None,
	reference_type=None,
	reference_name=None,
	debit=None,
	credit=None,
	exchange_rate=None,
):
	# Ensure exchange_rate is always numeric to avoid calculation errors
	if isinstance(exchange_rate, str):
		exchange_rate = flt(exchange_rate) or 1

	account_details = frappe.get_cached_value(
		"Account", account, ["account_type", "root_type", "account_currency", "company"], as_dict=1
	)

	if not account_details:
		frappe.throw(_("Please select correct account"))

	if not company:
		company = account_details.company

	if not account_currency:
		account_currency = account_details.account_currency

	company_currency = erpnext.get_company_currency(company)

	if account_currency != company_currency:
		if reference_type in ("Sales Invoice", "Purchase Invoice") and reference_name:
			exchange_rate = frappe.db.get_value(reference_type, reference_name, "conversion_rate")

		# The date used to retreive the exchange rate here is the date passed
		# in as an argument to this function.
		elif (not flt(exchange_rate) or flt(exchange_rate) == 1) and account_currency and posting_date:
			exchange_rate = _get_exchange_rate(account_currency, company_currency, posting_date)
	else:
		exchange_rate = 1

	# don't return None or 0 as it is multipled with a value and that value could be lost
	return exchange_rate or 1


@frappe.whitelist()
def get_average_exchange_rate(account):
	exchange_rate = 0
	bank_balance_in_account_currency = get_balance_on(account)
	if bank_balance_in_account_currency:
		bank_balance_in_company_currency = get_balance_on(account, in_account_currency=False)
		exchange_rate = bank_balance_in_company_currency / bank_balance_in_account_currency

	return exchange_rate


@frappe.whitelist()
def make_inter_company_journal_entry(name, voucher_type, company):
	journal_entry = frappe.new_doc("Journal Entry")
	journal_entry.voucher_type = voucher_type
	journal_entry.company = company
	journal_entry.posting_date = nowdate()
	journal_entry.inter_company_journal_entry_reference = name
	return journal_entry.as_dict()


@frappe.whitelist()
def make_reverse_journal_entry(source_name, target_doc=None):
	# WP GA-0001-05+06: block manual reversal while an active Auto Repeat (Reversal) is linked.
	# The user must cancel/disable the Auto Repeat before reversing manually.
	# Capability-checked so this is safe to ship before Auto Repeat gains repeat_type
	# (frappe.db.get_value returns None silently when the field doesn't exist on the doctype).
	# Find any Active, non-disabled Auto Repeat (Reversal) targeting this JE.
	# The earlier shape relied on JE.linked_auto_repeat being set on AR insert,
	# but the template hook doesn't write that back-link — it only stamps it
	# from the reversal handler. So scan Auto Repeat directly.
	#
	# Gate matches the scheduler's: status=='Active' AND !disabled. Auto
	# Repeat is NOT submittable, so docstatus checks would always fail.
	#
	# Exempt the Auto Repeat's OWN scheduled handler: it calls this function
	# to perform the very reversal the AR schedules. Without this, the guard
	# blocks the AR against itself (it is always Active+enabled at fire time),
	# so auto-reversal could never succeed. The flag is set only by
	# auto_repeat_handler.make_journal_entry_reversal and is not an API kwarg,
	# so the user-facing manual-reversal guard remains fully enforced.
	if not frappe.flags.get("in_auto_repeat_reversal") and frappe.get_meta(
		"Auto Repeat"
	).has_field("repeat_type"):
		linked_ar = frappe.db.get_value(
			"Auto Repeat",
			{
				"reference_doctype": "Journal Entry",
				"reference_document": source_name,
				"repeat_type": "Reversal",
				"status": "Active",
				"disabled": 0,
			},
			"name",
		)
		if linked_ar:
			frappe.throw(
				_(
					"{0} has an active Auto Repeat reversal {1}. "
					"Cancel or disable the Auto Repeat first before reversing manually."
				).format(
					frappe.bold(source_name),
					get_link_to_form("Auto Repeat", linked_ar),
				)
			)

	# WP GA-0001-01: block reversal of a reversal.
	source = frappe.db.get_value(
		"Journal Entry",
		source_name,
		["is_reversal", "reversal_of"],
		as_dict=True,
	)
	if source and (source.is_reversal or source.reversal_of):
		frappe.throw(
			_("Journal Entry {0} is itself a reversal. Reversing a reversal entry is not allowed.").format(
				get_link_to_form("Journal Entry", source_name)
			)
		)

	existing_reverse = frappe.db.exists(
		"Journal Entry", {"reversal_of": source_name, "docstatus": ["in", [0, 1]]}
	)
	if existing_reverse:
		frappe.throw(
			_("A Reverse Journal Entry {0} already exists for this Journal Entry.").format(
				get_link_to_form("Journal Entry", existing_reverse)
			)
		)

	from frappe.model.mapper import get_mapped_doc

	def post_process(source, target):
		target.reversal_of = source.name
		target.is_reversal = 1
		target.is_reversed = 0
		target.reversed_by = None
		target.respect_cost_center_allocation = 1
		# WP GA-0001-01: cheque_no / cheque_date have no_copy=1 in the JE
		# doctype JSON, so get_mapped_doc strips them. Explicitly carry them
		# over for Bank Entry / Cash Entry reversals — the reversal represents
		# the same banking transaction reversed, so the reference number and
		# date are the same. Without this, locking the (empty) fields combined
		# with Frappe v16's `hide_empty_read_only_fields` sysdefault hides
		# them on the form while mandatory_depends_on still requires them
		# server-side — unsubmittable reversal.
		target.cheque_no = source.cheque_no
		target.cheque_date = source.cheque_date
		# NOTE: is_advance is intentionally NOT carried over. A reversal flips
		# debit<->credit, so an advance row (e.g. a customer advance, which must
		# be a credit) would become a debit and fail the "Advance against
		# Customer must be credit" rule. The reversal of an advance is not itself
		# an advance, so it is left at its default ("No"). is_advance is locked
		# read-only on the reversal form (lock_reversal_fields) per WA-0001-01 #7,
		# but it is NOT diffed against the original (see validate_reversal_locked_fields).

	doclist = get_mapped_doc(
		"Journal Entry",
		source_name,
		{
			"Journal Entry": {"doctype": "Journal Entry", "validation": {"docstatus": ["=", 1]}},
			"Journal Entry Account": {
				"doctype": "Journal Entry Account",
				"field_map": {
					"account_currency": "account_currency",
					"exchange_rate": "exchange_rate",
					"debit_in_account_currency": "credit_in_account_currency",
					"debit": "credit",
					"credit_in_account_currency": "debit_in_account_currency",
					"credit": "debit",
					"reference_type": "reference_type",
					"reference_name": "reference_name",
				},
			},
		},
		target_doc,
		post_process,
	)

	return doclist


def _find_main_cost_center_for_leaf(leaf_cost_center, posting_date):
	"""Given a (potentially leaf) cost center that was posted on the original
	entry, return the main cost center whose allocation at ``posting_date``
	resolves to this leaf. If no allocation references the leaf, fall back to
	the leaf itself so ``distribute_gl_based_on_cost_center_allocation`` treats
	it normally at the reversal's posting date."""
	allocation = frappe.db.sql(
		"""
		SELECT parent.main_cost_center
		FROM `tabCost Center Allocation Percentage` child
		JOIN `tabCost Center Allocation` parent ON child.parent = parent.name
		WHERE child.cost_center = %(leaf)s
			AND parent.docstatus = 1
			AND parent.valid_from <= %(posting_date)s
		ORDER BY parent.valid_from DESC
		LIMIT 1
		""",
		{"leaf": leaf_cost_center, "posting_date": posting_date},
		as_dict=True,
	)
	if allocation:
		return allocation[0].main_cost_center
	return leaf_cost_center
