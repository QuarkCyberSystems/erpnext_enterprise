from collections import OrderedDict

import frappe
from frappe import _, qb
from frappe.query_builder import Criterion
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import flt, fmt_money, get_link_to_form

from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget
from erpnext.accounts.utils import get_fiscal_year


class BudgetExceededError(frappe.ValidationError):
	pass


class BudgetValidation:
	def __init__(self, doc: object | None = None, gl_map: list | None = None):
		if doc:
			self.document_type = doc.get("doctype")
			self.doc = doc
			self.company = doc.get("company")
			self.doc_date = doc.get("transaction_date")
		elif gl_map:
			# When GL Map is passed, there is a possibility of multiple fiscal year.
			# TODO: need to handle it
			self.document_type = "GL Map"
			self.gl_map = gl_map
			self.company = gl_map[0].company
			self.doc_date = gl_map[0].posting_date

		fy = get_fiscal_year(self.doc_date)
		self.fiscal_year = fy[0]
		self.fy_start_date = fy[1]
		self.fy_end_date = fy[2]
		self.get_dimensions()

	def validate(self):
		self.build_validation_map()
		self.validate_for_overbooking()

	def build_validation_map(self):
		self.build_budget_keys_and_map()
		self.build_doc_or_item_keys_and_map()
		self.find_overlap()

	def find_overlap(self):
		self.overlap = self.budget_keys & self.doc_or_item_keys
		self.to_validate = OrderedDict()

		for key in self.overlap:
			_obj = {
				"budget_amount": self.budget_map[key].budget_amount,
				"budget_doc": self.budget_map[key],
				"requested_amount": 0,
				"ordered_amount": 0,
				"actual_expense": 0,
			}
			_obj.update(
				{
					"accumulated_monthly_budget": get_accumulated_monthly_budget(
						self.budget_map[key].monthly_distribution,
						self.doc_date,
						self.fiscal_year,
						self.budget_map[key].budget_amount,
					)
				}
			)

			if self.document_type in ["Purchase Order", "Material Request"]:
				_obj.update({"items_to_process": self.doc_or_item_map[key]})
			elif self.document_type == "GL Map":
				_obj.update({"gl_to_process": self.doc_or_item_map[key]})

			self.to_validate[key] = OrderedDict(_obj)

	def validate_for_overbooking(self):
		for key, v in self.to_validate.items():
			self.get_ordered_amount(key)
			self.get_requested_amount(key)

			# Validation happens after submit for Purchase Order and
			# Material Request and so will be included in the query
			# result
			if self.document_type in ["Purchase Order", "Material Request"]:
				v["current_amount"] = 0
			elif self.document_type == "GL Map":
				v["current_amount"] = sum([x.debit - x.credit for x in v.get("gl_to_process", [])])

			# If limit breached, exit early
			self.handle_action(key, v)

			self.get_actual_expense(key)
			self.handle_action(key, v)

	def build_budget_keys_and_map(self):
		"""
		key structure - (dimension_type, dimension, GL account)
		"""
		_budgets = self.get_budget_records()
		self.budget_map = OrderedDict()
		for _bud in _budgets:
			budget_against = frappe.scrub(_bud.budget_against)
			dimension = _bud.get(budget_against)
			key = (budget_against, dimension, _bud.account)
			# TODO: ensure duplicate keys are not possible
			self.budget_map[key] = _bud
		self.budget_keys = self.budget_map.keys()

	def build_doc_or_item_keys_and_map(self):
		"""
		key structure - (dimension_type, dimension, GL account)
		"""
		self.doc_or_item_map = OrderedDict()
		if self.document_type in ["Purchase Order", "Material Request"]:
			for itm in self.doc.items:
				for dim in self.dimensions:
					if itm.get(dim.get("fieldname")):
						key = (dim.get("fieldname"), itm.get(dim.get("fieldname")), itm.expense_account)
						# TODO: How to handle duplicate items - same item with same dimension with same account
						self.doc_or_item_map.setdefault(key, []).append(itm)
		elif self.document_type == "GL Map":
			for gl in self.gl_map:
				for dim in self.dimensions:
					if gl.get(dim.get("fieldname")):
						key = (dim.get("fieldname"), gl.get(dim.get("fieldname")), gl.get("account"))
						self.doc_or_item_map.setdefault(key, []).append(gl)

		self.doc_or_item_keys = self.doc_or_item_map.keys()

	def get_dimensions(self):
		self.dimensions = []
		for _x in frappe.db.get_all("Accounting Dimension"):
			self.dimensions.append(frappe.get_doc("Accounting Dimension", _x.name))
		self.dimensions.extend(
			[
				{"fieldname": "cost_center", "document_type": "Cost Center"},
				{"fieldname": "project", "document_type": "Project"},
			]
		)

	def get_budget_records(self) -> list:
		bud = qb.DocType("Budget")
		bud_acc = qb.DocType("Budget Account")
		query = (
			qb.from_(bud)
			.inner_join(bud_acc)
			.on(bud.name == bud_acc.parent)
			.select(
				bud.name,
				bud.budget_against,
				bud.company,
				bud.applicable_on_material_request,
				bud.action_if_annual_budget_exceeded_on_mr,
				bud.action_if_accumulated_monthly_budget_exceeded_on_mr,
				bud.applicable_on_purchase_order,
				bud.action_if_annual_budget_exceeded_on_po,
				bud.action_if_accumulated_monthly_budget_exceeded_on_po,
				bud.applicable_on_booking_actual_expenses,
				bud.action_if_annual_budget_exceeded,
				bud.action_if_accumulated_monthly_budget_exceeded,
				bud_acc.account,
				bud_acc.budget_amount,
			)
			.where(bud.docstatus.eq(1) & bud.fiscal_year.eq(self.fiscal_year) & bud.company.eq(self.company))
		)

		# add dimension fields
		for x in self.dimensions:
			query = query.select(bud[x.get("fieldname")])

		_budgets = query.run(as_dict=True)
		return _budgets

	def get_ordered_amount(self, key: tuple | None = None):
		if key:
			items = set([x.item_code for x in self.doc.items])
			exp_accounts = set([x.expense_account for x in self.doc.items])

			po = qb.DocType("Purchase Order")
			poi = qb.DocType("Purchase Order Item")

			conditions = []
			conditions.append(po.company.eq(self.company))
			conditions.append(po.docstatus.eq(1))
			conditions.append(po.status.ne("Closed"))
			conditions.append(po.transaction_date[self.fy_start_date : self.fy_end_date])
			conditions.append(poi.amount.gt(poi.billed_amt))
			conditions.append(poi.expense_account.isin(exp_accounts))
			conditions.append(poi.item_code.isin(items))

			# key structure - (dimension_type, dimension, GL account)
			conditions.append(poi[key[0]].eq(key[1]))

			ordered_amount = (
				qb.from_(po)
				.inner_join(poi)
				.on(po.name == poi.parent)
				.select(Sum(IfNull(poi.amount, 0) - IfNull(poi.billed_amt, 0)).as_("amount"))
				.where(Criterion.all(conditions))
				.run(as_dict=True)
			)

			if ordered_amount:
				self.to_validate[key]["ordered_amount"] = ordered_amount[0].amount or 0

	def get_requested_amount(self, key: tuple | None = None):
		if key:
			items = set([x.item_code for x in self.doc.items])
			exp_accounts = set([x.expense_account for x in self.doc.items])

			mr = qb.DocType("Material Request")
			mri = qb.DocType("Material Request Item")

			conditions = []
			conditions.append(mr.company.eq(self.company))
			conditions.append(mr.docstatus.eq(1))
			conditions.append(mr.material_request_type.eq("Purchase"))
			conditions.append(mr.status.ne("Stopped"))
			conditions.append(mr.transaction_date[self.fy_start_date : self.fy_end_date])
			conditions.append(mri.expense_account.isin(exp_accounts))
			conditions.append(mri.item_code.isin(items))

			# key structure - (dimension_type, dimension, GL account)
			conditions.append(mri[key[0]].eq(key[1]))

			requested_amount = (
				qb.from_(mr)
				.inner_join(mri)
				.on(mr.name == mri.parent)
				.select((Sum(IfNull(mri.stock_qty, 0) - IfNull(mri.ordered_qty, 0)) * mri.rate).as_("amount"))
				.where(Criterion.all(conditions))
				.run(as_dict=True)
			)

			if requested_amount:
				self.to_validate[key]["requested_amount"] = requested_amount[0].amount or 0

	def get_actual_expense(self, key: tuple | None = None):
		if key:
			gl = qb.DocType("GL Entry")

			query = (
				qb.from_(gl)
				.select((Sum(gl.debit) - Sum(gl.credit)).as_("balance"))
				.where(
					gl.is_cancelled.eq(0)
					& gl.account.eq(key[2])
					& gl.fiscal_year.eq(self.fiscal_year)
					& gl.company.eq(self.company)
					& gl[key[0]].eq(key[1])
					& gl.posting_date[self.fy_start_date : self.fy_end_date]
				)
			)
			actual_expense = query.run(as_dict=True)
			if actual_expense:
				self.to_validate[key]["actual_expense"] = actual_expense[0].balance or 0

	def stop(self, msg):
		frappe.throw(msg, BudgetExceededError, title=_("Budget Exceeded"))

	def warn(self, msg):
		frappe.msgprint(msg, _("Budget Exceeded"))

	def handle_individual_doctype_action(
		self, config, budget, budget_amt, existing_amt, current_amt, acc_monthly_budget
	):
		if config.applies:
			currency = frappe.get_cached_value("Company", self.company, "default_currency")
			annual_diff = (existing_amt + current_amt) - budget_amt
			if annual_diff > 0:
				_msg = _(
					"Expenses have gone above budget by {} for {}".format(
						frappe.bold(fmt_money(annual_diff, currency=currency)),
						get_link_to_form("Budget", budget),
					)
				)

				if config.action_for_annual == "Warn":
					self.warn(_msg)

				if config.action_for_annual == "Stop":
					self.stop(_msg)

			monthly_diff = (existing_amt + current_amt) - acc_monthly_budget
			if monthly_diff > 0:
				_msg = _(
					"Expenses have gone above accumulated monthly budget by {} for {}.</br>Configured accumulated limit is {}".format(
						frappe.bold(fmt_money(monthly_diff, currency=currency)),
						get_link_to_form("Budget", budget),
						fmt_money(acc_monthly_budget, currency=currency),
					)
				)

				if config.action_for_monthly == "Warn":
					self.warn(_msg)

				if config.action_for_monthly == "Stop":
					self.stop(_msg)

	def handle_action(self, key, v_map):
		budget = v_map.get("budget_doc")
		actual_exp = v_map.get("actual_expense")
		ordered_amt = v_map.get("ordered_amount")
		requested_amt = v_map.get("requested_amount")
		current_amt = v_map.get("current_amount")
		budget_amt = v_map.get("budget_amount")
		acc_monthly_budget = v_map.get("accumulated_monthly_budget")

		self.handle_individual_doctype_action(
			frappe._dict(
				{
					"applies": budget.applicable_on_purchase_order,
					"action_for_annual": budget.action_if_annual_budget_exceeded_on_po,
					"action_for_monthly": budget.action_if_accumulated_monthly_budget_exceeded_on_po,
				}
			),
			budget.name,
			budget_amt,
			ordered_amt,
			current_amt,
			acc_monthly_budget,
		)
		self.handle_individual_doctype_action(
			frappe._dict(
				{
					"applies": budget.applicable_on_material_request,
					"action_for_annual": budget.action_if_annual_budget_exceeded_on_mr,
					"action_for_monthly": budget.action_if_accumulated_monthly_budget_exceeded_on_mr,
				}
			),
			budget.name,
			budget_amt,
			requested_amt,
			current_amt,
			acc_monthly_budget,
		)
		self.handle_individual_doctype_action(
			frappe._dict(
				{
					"applies": budget.applicable_on_booking_actual_expenses,
					"action_for_annual": budget.action_if_annual_budget_exceeded,
					"action_for_monthly": budget.action_if_accumulated_monthly_budget_exceeded,
				}
			),
			budget.name,
			budget_amt,
			actual_exp,
			current_amt,
			acc_monthly_budget,
		)

		total_diff = (ordered_amt + requested_amt + actual_exp + current_amt) - budget_amt
		if total_diff > 0:
			currency = frappe.get_cached_value("Company", self.company, "default_currency")
			_msg = _(
				"Annual Budget for Account {} against {} {} is {}. It will be exceeded by {}".format(
					frappe.bold(key[2]),
					frappe.bold(frappe.unscrub(key[0])),
					frappe.bold(key[1]),
					frappe.bold(fmt_money(budget_amt, currency=currency)),
					frappe.bold(fmt_money(total_diff, currency=currency)),
				)
			)
			self.stop(_msg)
