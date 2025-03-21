# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _, qb, scrub
from frappe.query_builder import Criterion, Tuple
from frappe.query_builder.functions import IfNull
from frappe.utils import getdate, nowdate

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.financial_statements import get_cost_centers_with_children


class PartyLedgerSummaryReport:
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.filters.from_date = getdate(self.filters.from_date or nowdate())
		self.filters.to_date = getdate(self.filters.to_date or nowdate())

		if not self.filters.get("company"):
			self.filters["company"] = frappe.db.get_single_value("Global Defaults", "default_company")

	def run(self, args):
		if self.filters.from_date > self.filters.to_date:
			frappe.throw(_("From Date must be before To Date"))

		self.filters.party_type = args.get("party_type")
		self.party_naming_by = frappe.db.get_single_value(args.get("naming_by")[0], args.get("naming_by")[1])

		self.get_paty_details()

		if not self.parties:
			return [], []

		self.get_gl_entries()
		self.get_return_invoices()
		self.get_party_adjustment_amounts()

		columns = self.get_columns()
		data = self.get_data()

		return columns, data

	def get_additional_fields(self):
		additional_fields = []

		if self.filters.party_type == "Customer":
			additional_fields = ["customer_name", "territory", "customer_group", "default_sales_partner"]
		else:
			additional_fields = ["supplier_name", "supplier_group"]

		return additional_fields

	def prepare_party_conditions(self, doctype):
		conditions = []
		group_field = "customer_group" if self.filters.party_type == "Customer" else "supplier_group"

		if self.filters.party:
			conditions.append(doctype.name == self.filters.party)

		if self.filters.territory:
			conditions.append(doctype.territory == self.filters.territory)

		if self.filters.get(group_field):
			conditions.append(doctype.get(group_field) == self.filters.get(group_field))

		if self.filters.payment_terms_template:
			conditions.append(doctype.payment_terms == self.filters.payment_terms_template)

		if self.filters.sales_partner:
			conditions.append(doctype.default_sales_partner == self.filters.sales_partner)

		if self.filters.sales_person:
			sales_team = qb.DocType("Sales Team")
			conditions.append(
				(doctype.name).isin(
					qb.from_(sales_team)
					.select(sales_team.parent)
					.where(sales_team.sales_person == self.filters.sales_person)
				)
			)

		return conditions

	def get_paty_details(self):
		"""
		Additional Columns for 'User Permission' based access control
		"""
		self.parties = []
		self.party_details = frappe._dict()
		party_type = self.filters.party_type
		additional_fields = self.get_additional_fields()

		doctype = qb.DocType(party_type)
		conditions = self.prepare_party_conditions(doctype)
		party_details = (
			qb.from_(doctype)
			.select(doctype.name.as_("party"), *additional_fields)
			.where(Criterion.all(conditions))
			.run(as_dict=True)
		)

		for row in party_details:
			self.parties.append(row.party)
			self.party_details[row.party] = row

	def get_columns(self):
		columns = [
			{
				"label": _(self.filters.party_type),
				"fieldtype": "Link",
				"fieldname": "party",
				"options": self.filters.party_type,
				"width": 200,
			}
		]

		if self.party_naming_by == "Naming Series":
			columns.append(
				{
					"label": _(self.filters.party_type + "Name"),
					"fieldtype": "Data",
					"fieldname": "party_name",
					"width": 110,
				}
			)

		credit_or_debit_note = "Credit Note" if self.filters.party_type == "Customer" else "Debit Note"

		columns += [
			{
				"label": _("Opening Balance"),
				"fieldname": "opening_balance",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Invoiced Amount"),
				"fieldname": "invoiced_amount",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Paid Amount"),
				"fieldname": "paid_amount",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _(credit_or_debit_note),
				"fieldname": "return_amount",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
		]

		for account in self.party_adjustment_accounts:
			columns.append(
				{
					"label": account,
					"fieldname": "adj_" + scrub(account),
					"fieldtype": "Currency",
					"options": "currency",
					"width": 120,
					"is_adjustment": 1,
				}
			)

		columns += [
			{
				"label": _("Closing Balance"),
				"fieldname": "closing_balance",
				"fieldtype": "Currency",
				"options": "currency",
				"width": 120,
			},
			{
				"label": _("Currency"),
				"fieldname": "currency",
				"fieldtype": "Link",
				"options": "Currency",
				"width": 50,
			},
		]

		# Hidden columns for handling 'User Permissions'
		if self.filters.party_type == "Customer":
			columns += [
				{
					"label": _("Territory"),
					"fieldname": "territory",
					"fieldtype": "Link",
					"options": "Territory",
					"hidden": 1,
				},
				{
					"label": _("Customer Group"),
					"fieldname": "customer_group",
					"fieldtype": "Link",
					"options": "Customer Group",
					"hidden": 1,
				},
			]
		else:
			columns += [
				{
					"label": _("Supplier Group"),
					"fieldname": "supplier_group",
					"fieldtype": "Link",
					"options": "Supplier Group",
					"hidden": 1,
				}
			]

		return columns

	def get_data(self):
		company_currency = frappe.get_cached_value("Company", self.filters.get("company"), "default_currency")
		invoice_dr_or_cr = "debit" if self.filters.party_type == "Customer" else "credit"
		reverse_dr_or_cr = "credit" if self.filters.party_type == "Customer" else "debit"

		self.party_data = frappe._dict({})
		for gle in self.gl_entries:
			party_details = self.party_details.get(gle.party)
			self.party_data.setdefault(
				gle.party,
				frappe._dict(
					{
						**party_details,
						"party_name": gle.party,
						"opening_balance": 0,
						"invoiced_amount": 0,
						"paid_amount": 0,
						"return_amount": 0,
						"closing_balance": 0,
						"currency": company_currency,
					}
				),
			)

			amount = gle.get(invoice_dr_or_cr) - gle.get(reverse_dr_or_cr)
			self.party_data[gle.party].closing_balance += amount

			if gle.posting_date < self.filters.from_date or gle.is_opening == "Yes":
				self.party_data[gle.party].opening_balance += amount
			else:
				if amount > 0:
					self.party_data[gle.party].invoiced_amount += amount
				elif gle.voucher_no in self.return_invoices:
					self.party_data[gle.party].return_amount -= amount
				else:
					self.party_data[gle.party].paid_amount -= amount

		out = []
		for party, row in self.party_data.items():
			if (
				row.opening_balance
				or row.invoiced_amount
				or row.paid_amount
				or row.return_amount
				or row.closing_amount
			):
				total_party_adjustment = sum(
					amount for amount in self.party_adjustment_details.get(party, {}).values()
				)
				row.paid_amount -= total_party_adjustment

				adjustments = self.party_adjustment_details.get(party, {})
				for account in self.party_adjustment_accounts:
					row["adj_" + scrub(account)] = adjustments.get(account, 0)

				out.append(row)

		return out

	def get_gl_entries(self):
		gle = qb.DocType("GL Entry")
		query = (
			qb.from_(gle)
			.select(
				gle.posting_date,
				gle.party,
				gle.voucher_type,
				gle.voucher_no,
				gle.against_voucher_type,
				gle.against_voucher,
				gle.debit,
				gle.credit,
				gle.is_opening,
			)
			.where(
				(gle.docstatus < 2)
				& (gle.is_cancelled == 0)
				& (gle.party_type == self.filters.party_type)
				& (IfNull(gle.party, "") != "")
				& (gle.posting_date <= self.filters.to_date)
				& (gle.party.isin(self.parties))
			)
		)

		query = self.prepare_conditions(query)

		self.gl_entries = query.run(as_dict=True)

	def prepare_conditions(self, query):
		gle = qb.DocType("GL Entry")
		if self.filters.company:
			query = query.where(gle.company == self.filters.company)

		if self.filters.finance_book:
			query = query.where(IfNull(gle.finance_book, "") == self.filters.finance_book)

		if self.filters.cost_center:
			self.filters.cost_center = get_cost_centers_with_children(self.filters.cost_center)
			query = query.where((gle.cost_center).isin(self.filters.cost_center))

		if self.filters.project:
			query = query.where((gle.project).isin(self.filters.project))

		accounting_dimensions = get_accounting_dimensions(as_list=False)

		if accounting_dimensions:
			for dimension in accounting_dimensions:
				if self.filters.get(dimension.fieldname):
					if frappe.get_cached_value("DocType", dimension.document_type, "is_tree"):
						self.filters[dimension.fieldname] = get_dimension_with_children(
							dimension.document_type, self.filters.get(dimension.fieldname)
						)
						query = query.where(
							(gle[dimension.fieldname]).isin(self.filters.get(dimension.fieldname))
						)
					else:
						query = query.where(
							(gle[dimension.fieldname]).isin(self.filters.get(dimension.fieldname))
						)

		return query

	def get_return_invoices(self):
		doctype = "Sales Invoice" if self.filters.party_type == "Customer" else "Purchase Invoice"
		name_field = "customer" if self.filters.party_type == "Customer" else "supplier"
		self.return_invoices = [
			d.name
			for d in frappe.get_all(
				doctype,
				filters={
					"is_return": 1,
					"docstatus": 1,
					"posting_date": ["between", [self.filters.from_date, self.filters.to_date]],
					name_field: ["in", self.parties],
				},
			)
		]

	def get_party_adjustment_amounts(self):
		account_type = "Expense Account" if self.filters.party_type == "Customer" else "Income Account"

		invoice_dr_or_cr = "debit" if self.filters.party_type == "Customer" else "credit"
		reverse_dr_or_cr = "credit" if self.filters.party_type == "Customer" else "debit"
		round_off_account = frappe.get_cached_value("Company", self.filters.company, "round_off_account")

		current_period_vouchers = set()
		for gle in self.gl_entries:
			if gle.posting_date >= self.filters.from_date and gle.posting_date <= self.filters.to_date:
				current_period_vouchers.add((gle.voucher_type, gle.voucher_no))

		gl = qb.DocType("GL Entry")
		query = (
			qb.from_(gl)
			.select(
				gl.posting_date, gl.account, gl.party, gl.voucher_type, gl.voucher_no, gl.debit, gl.credit
			)
			.where(
				(gl.docstatus < 2)
				& (gl.is_cancelled == 0)
				& (gl.posting_date.gte(self.filters.from_date))
				& (gl.posting_date.lte(self.filters.to_date))
				& (Tuple((gl.voucher_type, gl.voucher_no)).isin(current_period_vouchers))
			)
		)
		query = self.prepare_conditions(query)
		gl_entries = query.run(as_dict=True)

		self.party_adjustment_details = {}
		self.party_adjustment_accounts = set()
		adjustment_voucher_entries = {}
		for gle in gl_entries:
			adjustment_voucher_entries.setdefault((gle.voucher_type, gle.voucher_no), [])
			adjustment_voucher_entries[(gle.voucher_type, gle.voucher_no)].append(gle)

		for voucher_gl_entries in adjustment_voucher_entries.values():
			parties = {}
			accounts = {}
			has_irrelevant_entry = False

			for gle in voucher_gl_entries:
				if gle.account == round_off_account:
					continue
				elif gle.party:
					parties.setdefault(gle.party, 0)
					parties[gle.party] += gle.get(reverse_dr_or_cr) - gle.get(invoice_dr_or_cr)
				elif frappe.get_cached_value("Account", gle.account, "account_type") == account_type:
					accounts.setdefault(gle.account, 0)
					accounts[gle.account] += gle.get(invoice_dr_or_cr) - gle.get(reverse_dr_or_cr)
				else:
					has_irrelevant_entry = True

			if parties and accounts:
				if len(parties) == 1:
					party = next(iter(parties.keys()))
					for account, amount in accounts.items():
						self.party_adjustment_accounts.add(account)
						self.party_adjustment_details.setdefault(party, {})
						self.party_adjustment_details[party].setdefault(account, 0)
						self.party_adjustment_details[party][account] += amount
				elif len(accounts) == 1 and not has_irrelevant_entry:
					account = next(iter(accounts.keys()))
					self.party_adjustment_accounts.add(account)
					for party, amount in parties.items():
						self.party_adjustment_details.setdefault(party, {})
						self.party_adjustment_details[party].setdefault(account, 0)
						self.party_adjustment_details[party][account] += amount


def execute(filters=None):
	args = {
		"party_type": "Customer",
		"naming_by": ["Selling Settings", "cust_master_name"],
	}
	return PartyLedgerSummaryReport(filters).run(args)
