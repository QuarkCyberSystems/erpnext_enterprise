# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


from datetime import date

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, flt, fmt_money, get_last_day, getdate, month_diff
from frappe.utils.data import get_first_day

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)
from erpnext.accounts.utils import get_fiscal_year


class BudgetError(frappe.ValidationError):
	pass


class DuplicateBudgetError(frappe.ValidationError):
	pass


class Budget(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.budget_distribution.budget_distribution import BudgetDistribution

		account: DF.Link
		action_if_accumulated_monthly_budget_exceeded: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_accumulated_monthly_budget_exceeded_on_mr: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_accumulated_monthly_budget_exceeded_on_po: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_accumulated_monthly_exceeded_on_cumulative_expense: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_annual_budget_exceeded: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_annual_budget_exceeded_on_mr: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_annual_budget_exceeded_on_po: DF.Literal["", "Stop", "Warn", "Ignore"]
		action_if_annual_exceeded_on_cumulative_expense: DF.Literal["", "Stop", "Warn", "Ignore"]
		allocation_frequency: DF.Literal["Monthly", "Quarterly", "Half-Yearly", "Yearly", "Date Range"]
		amended_from: DF.Link | None
		applicable_on_booking_actual_expenses: DF.Check
		applicable_on_cumulative_expense: DF.Check
		applicable_on_material_request: DF.Check
		applicable_on_purchase_order: DF.Check
		budget_against: DF.Literal["", "Cost Center", "Project"]
		budget_amount: DF.Currency
		budget_distribution: DF.Table[BudgetDistribution]
		budget_end_date: DF.Date
		budget_start_date: DF.Date
		company: DF.Link
		cost_center: DF.Link | None
		distribution_type: DF.Literal["Amount", "Percent"]
		fiscal_year: DF.Link
		naming_series: DF.Literal["BUDGET-.YYYY.-"]
		project: DF.Link | None
		revision_of: DF.Data | None
	# end: auto-generated types

	def validate(self):
		if not self.get(frappe.scrub(self.budget_against)):
			frappe.throw(_("{0} is mandatory").format(self.budget_against))
		self.validate_duplicate()
		self.validate_account()
		self.set_null_value()
		self.validate_applicable_for()

	def validate_duplicate(self):
		budget_against_field = frappe.scrub(self.budget_against)
		budget_against = self.get(budget_against_field)
		account = self.account

		if not account:
			return

		existing_budget = frappe.db.get_all(
			"Budget",
			filters={
				"docstatus": ("<", 2),
				"company": self.company,
				budget_against_field: budget_against,
				"fiscal_year": self.fiscal_year,
				"account": account,
				"name": ("!=", self.name),
			},
			fields=["name", "account"],
		)

		if existing_budget:
			d = existing_budget[0]
			frappe.throw(
				_("Another Budget record '{0}' already exists against {1} '{2}' and account '{3}'").format(
					d.name, self.budget_against, budget_against, d.account
				),
				DuplicateBudgetError,
			)

	def validate_account(self):
		if not self.account:
			frappe.throw(_("Account is mandatory"))

		account_details = frappe.get_cached_value(
			"Account", self.account, ["is_group", "company", "report_type"], as_dict=1
		)

		if account_details.is_group:
			frappe.throw(_("Budget cannot be assigned against Group Account {0}").format(self.account))
		elif account_details.company != self.company:
			frappe.throw(_("Account {0} does not belong to company {1}").format(self.account, self.company))
		elif account_details.report_type != "Profit and Loss":
			frappe.throw(
				_("Budget cannot be assigned against {0}, as it's not an Income or Expense account").format(
					self.account
				)
			)

	def set_null_value(self):
		if self.budget_against == "Cost Center":
			self.project = None
		else:
			self.cost_center = None

	def validate_applicable_for(self):
		if self.applicable_on_material_request and not (
			self.applicable_on_purchase_order and self.applicable_on_booking_actual_expenses
		):
			frappe.throw(
				_("Please enable Applicable on Purchase Order and Applicable on Booking Actual Expenses")
			)

		elif self.applicable_on_purchase_order and not (self.applicable_on_booking_actual_expenses):
			frappe.throw(_("Please enable Applicable on Booking Actual Expenses"))

		elif not (
			self.applicable_on_material_request
			or self.applicable_on_purchase_order
			or self.applicable_on_booking_actual_expenses
		):
			self.applicable_on_booking_actual_expenses = 1

	def before_save(self):
		self.allocate_budget()

	def allocate_budget(self):
		if self.revision_of:
			return

		self.set("budget_distribution", [])
		if not (self.budget_start_date and self.budget_end_date and self.allocation_frequency):
			return

		start = getdate(self.budget_start_date)
		end = getdate(self.budget_end_date)
		freq = self.allocation_frequency

		months = month_diff(end, start)
		if freq == "Monthly":
			total_periods = months
		elif freq == "Quarterly":
			total_periods = months // 3 + (1 if months % 3 else 0)
		elif freq == "Half-Yearly":
			total_periods = months // 6 + (1 if months % 6 else 0)
		else:
			total_periods = end.year - start.year + 1

		if self.distribution_type == "Amount":
			per_row = flt(self.budget_amount / total_periods, 2)
		else:
			per_row = flt(100 / total_periods, 2)

		assigned = 0
		current = start

		while current <= end:
			row = self.append("budget_distribution", {})

			if freq == "Monthly":
				row.start_date = get_first_day(current)
				row.end_date = get_last_day(current)
				current = add_months(current, 1)
			elif freq == "Quarterly":
				month = ((current.month - 1) // 3) * 3 + 1
				quarter_start = date(current.year, month, 1)
				quarter_end = get_last_day(add_months(quarter_start, 2))
				row.start_date = quarter_start
				row.end_date = min(quarter_end, end)
				current = add_months(quarter_start, 3)
			elif freq == "Half-Yearly":
				half = 1 if current.month <= 6 else 2
				half_start = date(current.year, 1, 1) if half == 1 else date(current.year, 7, 1)
				half_end = date(current.year, 6, 30) if half == 1 else date(current.year, 12, 31)
				row.start_date = half_start
				row.end_date = min(half_end, end)
				current = add_months(half_start, 6)
			else:  # Yearly
				year_start = date(current.year, 1, 1)
				year_end = date(current.year, 12, 31)
				row.start_date = year_start
				row.end_date = min(year_end, end)
				current = date(current.year + 1, 1, 1)

			if self.distribution_type == "Amount":
				if len(self.budget_distribution) == total_periods:
					row.amount = flt(self.budget_amount - assigned)

				else:
					row.amount = per_row
					assigned += per_row
				row.percent = flt(row.amount * 100 / self.budget_amount)
			else:
				if len(self.budget_distribution) == total_periods:
					row.percent = flt(100 - assigned)
				else:
					row.percent = per_row
					assigned += per_row
				row.amount = flt(row.percent * self.budget_amount / 100)


def validate_expense_against_budget(args, expense_amount=0):
	args = frappe._dict(args)
	if not frappe.db.count("Budget", cache=True):
		return

	if not args.fiscal_year:
		args.fiscal_year = get_fiscal_year(args.get("posting_date"), company=args.get("company"))[0]

	if args.get("company"):
		frappe.flags.exception_approver_role = frappe.get_cached_value(
			"Company", args.get("company"), "exception_budget_approver_role"
		)

	if not frappe.db.get_value("Budget", {"fiscal_year": args.fiscal_year, "company": args.company}):
		return

	if not args.account:
		args.account = args.get("expense_account")

	if not (args.get("account") and args.get("cost_center")) and args.item_code:
		args.cost_center, args.account = get_item_details(args)

	if not args.account:
		return

	default_dimensions = [
		{
			"fieldname": "project",
			"document_type": "Project",
		},
		{
			"fieldname": "cost_center",
			"document_type": "Cost Center",
		},
	]

	for dimension in default_dimensions + get_accounting_dimensions(as_list=False):
		budget_against = dimension.get("fieldname")

		if (
			args.get(budget_against)
			and args.account
			and (frappe.get_cached_value("Account", args.account, "root_type") == "Expense")
		):
			doctype = dimension.get("document_type")

			if frappe.get_cached_value("DocType", doctype, "is_tree"):
				lft, rgt = frappe.get_cached_value(doctype, args.get(budget_against), ["lft", "rgt"])
				condition = f"""and exists(select name from `tab{doctype}`
					where lft<={lft} and rgt>={rgt} and name=b.{budget_against})"""  # nosec
				args.is_tree = True
			else:
				condition = f"and b.{budget_against}={frappe.db.escape(args.get(budget_against))}"
				args.is_tree = False

			args.budget_against_field = budget_against
			args.budget_against_doctype = doctype

			budget_records = frappe.db.sql(
				f"""
				select
					b.name, b.{budget_against} as budget_against, b.budget_amount, b.monthly_distribution,
					ifnull(b.applicable_on_material_request, 0) as for_material_request,
					ifnull(applicable_on_purchase_order, 0) as for_purchase_order,
					ifnull(applicable_on_booking_actual_expenses,0) as for_actual_expenses,
					b.action_if_annual_budget_exceeded, b.action_if_accumulated_monthly_budget_exceeded,
					b.action_if_annual_budget_exceeded_on_mr, b.action_if_accumulated_monthly_budget_exceeded_on_mr,
					b.action_if_annual_budget_exceeded_on_po, b.action_if_accumulated_monthly_budget_exceeded_on_po
				from
					`tabBudget` b
				where
					b.fiscal_year=%s
					and b.account=%s and b.docstatus=1
					{condition}
			""",
				(args.fiscal_year, args.account),
				as_dict=True,
			)  # nosec

			if budget_records:
				validate_budget_records(args, budget_records, expense_amount)


def validate_budget_records(args, budget_records, expense_amount):
	for budget in budget_records:
		if flt(budget.budget_amount):
			yearly_action, monthly_action = get_actions(args, budget)
			args["for_material_request"] = budget.for_material_request
			args["for_purchase_order"] = budget.for_purchase_order

			if yearly_action in ("Stop", "Warn"):
				compare_expense_with_budget(
					args,
					flt(budget.budget_amount),
					_("Annual"),
					yearly_action,
					budget.budget_against,
					expense_amount,
				)

			if monthly_action in ["Stop", "Warn"]:
				budget_amount = get_accumulated_monthly_budget(budget.name, args.posting_date)

				args["month_end_date"] = get_last_day(args.posting_date)

				compare_expense_with_budget(
					args,
					budget_amount,
					_("Accumulated Monthly"),
					monthly_action,
					budget.budget_against,
					expense_amount,
				)


def compare_expense_with_budget(args, budget_amount, action_for, action, budget_against, amount=0):
	args.actual_expense, args.requested_amount, args.ordered_amount = get_actual_expense(args), 0, 0
	if not amount:
		args.requested_amount, args.ordered_amount = get_requested_amount(args), get_ordered_amount(args)

		if args.get("doctype") == "Material Request" and args.for_material_request:
			amount = args.requested_amount + args.ordered_amount

		elif args.get("doctype") == "Purchase Order" and args.for_purchase_order:
			amount = args.ordered_amount

	total_expense = args.actual_expense + amount

	if total_expense > budget_amount:
		if args.actual_expense > budget_amount:
			diff = args.actual_expense - budget_amount
			_msg = _("{0} Budget for Account {1} against {2} {3} is {4}. It is already exceeded by {5}.")
		else:
			diff = total_expense - budget_amount
			_msg = _("{0} Budget for Account {1} against {2} {3} is {4}. It will be exceeded by {5}.")

		currency = frappe.get_cached_value("Company", args.company, "default_currency")
		msg = _msg.format(
			_(action_for),
			frappe.bold(args.account),
			frappe.unscrub(args.budget_against_field),
			frappe.bold(budget_against),
			frappe.bold(fmt_money(budget_amount, currency=currency)),
			frappe.bold(fmt_money(diff, currency=currency)),
		)

		msg += get_expense_breakup(args, currency, budget_against)

		if frappe.flags.exception_approver_role and frappe.flags.exception_approver_role in frappe.get_roles(
			frappe.session.user
		):
			action = "Warn"

		if action == "Stop":
			frappe.throw(msg, BudgetError, title=_("Budget Exceeded"))
		else:
			frappe.msgprint(msg, indicator="orange", title=_("Budget Exceeded"))


def get_expense_breakup(args, currency, budget_against):
	msg = "<hr> {{ _('Total Expenses booked through') }} - <ul>"

	common_filters = frappe._dict(
		{
			args.budget_against_field: budget_against,
			"account": args.account,
			"company": args.company,
		}
	)

	msg += (
		"<li>"
		+ frappe.utils.get_link_to_report(
			"General Ledger",
			label=_("Actual Expenses"),
			filters=common_filters.copy().update(
				{
					"from_date": frappe.get_cached_value("Fiscal Year", args.fiscal_year, "year_start_date"),
					"to_date": frappe.get_cached_value("Fiscal Year", args.fiscal_year, "year_end_date"),
					"is_cancelled": 0,
				}
			),
		)
		+ " - "
		+ frappe.bold(fmt_money(args.actual_expense, currency=currency))
		+ "</li>"
	)

	msg += (
		"<li>"
		+ frappe.utils.get_link_to_report(
			"Material Request",
			label=_("Material Requests"),
			report_type="Report Builder",
			doctype="Material Request",
			filters=common_filters.copy().update(
				{
					"status": [["!=", "Stopped"]],
					"docstatus": 1,
					"material_request_type": "Purchase",
					"schedule_date": [["fiscal year", "2023-2024"]],
					"item_code": args.item_code,
					"per_ordered": [["<", 100]],
				}
			),
		)
		+ " - "
		+ frappe.bold(fmt_money(args.requested_amount, currency=currency))
		+ "</li>"
	)

	msg += (
		"<li>"
		+ frappe.utils.get_link_to_report(
			"Purchase Order",
			label=_("Unbilled Orders"),
			report_type="Report Builder",
			doctype="Purchase Order",
			filters=common_filters.copy().update(
				{
					"status": [["!=", "Closed"]],
					"docstatus": 1,
					"transaction_date": [["fiscal year", "2023-2024"]],
					"item_code": args.item_code,
					"per_billed": [["<", 100]],
				}
			),
		)
		+ " - "
		+ frappe.bold(fmt_money(args.ordered_amount, currency=currency))
		+ "</li></ul>"
	)

	return msg


def get_actions(args, budget):
	yearly_action = budget.action_if_annual_budget_exceeded
	monthly_action = budget.action_if_accumulated_monthly_budget_exceeded

	if args.get("doctype") == "Material Request" and budget.for_material_request:
		yearly_action = budget.action_if_annual_budget_exceeded_on_mr
		monthly_action = budget.action_if_accumulated_monthly_budget_exceeded_on_mr

	elif args.get("doctype") == "Purchase Order" and budget.for_purchase_order:
		yearly_action = budget.action_if_annual_budget_exceeded_on_po
		monthly_action = budget.action_if_accumulated_monthly_budget_exceeded_on_po

	return yearly_action, monthly_action


def get_requested_amount(args):
	item_code = args.get("item_code")
	condition = get_other_condition(args, "Material Request")

	data = frappe.db.sql(
		""" select ifnull((sum(child.stock_qty - child.ordered_qty) * rate), 0) as amount
		from `tabMaterial Request Item` child, `tabMaterial Request` parent where parent.name = child.parent and
		child.item_code = %s and parent.docstatus = 1 and child.stock_qty > child.ordered_qty and {} and
		parent.material_request_type = 'Purchase' and parent.status != 'Stopped'""".format(condition),
		item_code,
		as_list=1,
	)

	return data[0][0] if data else 0


def get_ordered_amount(args):
	item_code = args.get("item_code")
	condition = get_other_condition(args, "Purchase Order")

	data = frappe.db.sql(
		f""" select ifnull(sum(child.amount - child.billed_amt), 0) as amount
		from `tabPurchase Order Item` child, `tabPurchase Order` parent where
		parent.name = child.parent and child.item_code = %s and parent.docstatus = 1 and child.amount > child.billed_amt
		and parent.status != 'Closed' and {condition}""",
		item_code,
		as_list=1,
	)

	return data[0][0] if data else 0


def get_other_condition(args, for_doc):
	condition = "expense_account = '%s'" % (args.expense_account)
	budget_against_field = args.get("budget_against_field")

	if budget_against_field and args.get(budget_against_field):
		condition += f" and child.{budget_against_field} = '{args.get(budget_against_field)}'"

	if args.get("fiscal_year"):
		date_field = "schedule_date" if for_doc == "Material Request" else "transaction_date"
		start_date, end_date = frappe.get_cached_value(
			"Fiscal Year", args.get("fiscal_year"), ["year_start_date", "year_end_date"]
		)

		condition += f""" and parent.{date_field}
			between '{start_date}' and '{end_date}' """

	return condition


def get_actual_expense(args):
	if not args.budget_against_doctype:
		args.budget_against_doctype = frappe.unscrub(args.budget_against_field)

	budget_against_field = args.get("budget_against_field")
	condition1 = " and gle.posting_date <= %(month_end_date)s" if args.get("month_end_date") else ""

	if args.is_tree:
		lft_rgt = frappe.db.get_value(
			args.budget_against_doctype, args.get(budget_against_field), ["lft", "rgt"], as_dict=1
		)

		args.update(lft_rgt)

		condition2 = f"""and exists(select name from `tab{args.budget_against_doctype}`
			where lft>=%(lft)s and rgt<=%(rgt)s
			and name=gle.{budget_against_field})"""
	else:
		condition2 = f"""and exists(select name from `tab{args.budget_against_doctype}`
		where name=gle.{budget_against_field} and
		gle.{budget_against_field} = %({budget_against_field})s)"""

	amount = flt(
		frappe.db.sql(
			f"""
		select sum(gle.debit) - sum(gle.credit)
		from `tabGL Entry` gle
		where
			is_cancelled = 0
			and gle.account=%(account)s
			{condition1}
			and gle.fiscal_year=%(fiscal_year)s
			and gle.company=%(company)s
			and gle.docstatus=1
			{condition2}
	""",
			(args),
		)[0][0]
	)  # nosec

	return amount


def get_accumulated_monthly_budget(budget_name, posting_date):
	posting_date = getdate(posting_date)

	bd = frappe.qb.DocType("Budget Distribution")
	b = frappe.qb.DocType("Budget")

	result = (
		frappe.qb.from_(bd)
		.join(b)
		.on(bd.parent == b.name)
		.select(Sum(bd.amount).as_("accumulated_amount"))
		.where(b.name == budget_name)
		.where(bd.end_date >= posting_date)
		.run(as_dict=True)
	)

	return flt(result[0]["accumulated_amount"]) if result else 0.0


def get_item_details(args):
	cost_center, expense_account = None, None

	if not args.get("company"):
		return cost_center, expense_account

	if args.item_code:
		item_defaults = frappe.db.get_value(
			"Item Default",
			{"parent": args.item_code, "company": args.get("company")},
			["buying_cost_center", "expense_account"],
		)
		if item_defaults:
			cost_center, expense_account = item_defaults

	if not (cost_center and expense_account):
		for doctype in ["Item Group", "Company"]:
			data = get_expense_cost_center(doctype, args)

			if not cost_center and data:
				cost_center = data[0]

			if not expense_account and data:
				expense_account = data[1]

			if cost_center and expense_account:
				return cost_center, expense_account

	return cost_center, expense_account


def get_expense_cost_center(doctype, args):
	if doctype == "Item Group":
		return frappe.db.get_value(
			"Item Default",
			{"parent": args.get(frappe.scrub(doctype)), "company": args.get("company")},
			["buying_cost_center", "expense_account"],
		)
	else:
		return frappe.db.get_value(
			doctype, args.get(frappe.scrub(doctype)), ["cost_center", "default_expense_account"]
		)


@frappe.whitelist()
def revise_budget(budget_name):
	old_budget = frappe.get_doc("Budget", budget_name)

	if old_budget.docstatus == 1:
		old_budget.cancel()
		frappe.db.commit()

	new_budget = frappe.copy_doc(old_budget)
	new_budget.docstatus = 0
	new_budget.revision_of = old_budget.name
	new_budget.posting_date = frappe.utils.nowdate()
	new_budget.insert()

	return new_budget.name
