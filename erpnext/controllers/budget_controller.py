from collections import OrderedDict

import frappe
from frappe import qb
from frappe.query_builder import Criterion
from frappe.query_builder.functions import IfNull, Sum

from erpnext.accounts.utils import get_fiscal_year


class BudgetValidation:
	def __init__(self, doc: object):
		self.doc = doc
		self.company = doc.get("company")
		self.doc_date = (
			doc.get("transaction_date") if doc.get("doctype") == "Purchase Order" else doc.get("posting_date")
		)
		fy = get_fiscal_year(self.doc_date)
		self.fiscal_year = fy[0]
		self.fy_start_date = fy[1]
		self.fy_end_date = fy[2]
		self.get_dimensions()
		# When GL Map is passed, there is a possibility of multiple fiscal year.
		# TODO: need to handle it

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

	def build_budget_keys_and_map(self):
		"""
		key structure - (dimension_type, dimension, GL account)
		"""
		_budgets = self.get_budget_records()
		_keys = []
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
		_key = []
		for itm in self.doc.items:
			for dim in self.dimensions:
				if itm.get(dim.get("fieldname")):
					key = (dim.get("fieldname"), itm.get(dim.get("fieldname")), itm.expense_account)
					# TODO: How to handle duplicate items - same item with same dimension with same account
					self.doc_or_item_map.setdefault(key, []).append(itm)
		self.doc_or_item_keys = self.doc_or_item_map.keys()

	def build_validation_map(self):
		self.overlap = self.budget_keys & self.doc_or_item_keys
		self.to_validate = OrderedDict()

		for key in self.overlap:
			self.to_validate[key] = OrderedDict(
				{
					"budget_amount": self.budget_map[key].budget_amount,
					"items_to_process": self.doc_or_item_map[key],
					"requested_amount": 0,
					"ordered_amount": 0,
				}
			)

	def validate(self):
		self.build_budget_keys_and_map()
		self.build_doc_or_item_keys_and_map()
		self.build_validation_map()
		self.validate_for_overbooking()

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
				self.to_validate[key]["ordered_amount"] = ordered_amount[0].amount

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
			conditions.append(mri.amount.gt(mri.billed_amt))
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
				self.to_validate[key]["requested_amount"] = requested_amount[0].amount

	def validate_for_overbooking(self):
		# TODO: Need to fetch historical amount and add them to the current document
		# TODO: handle applicable checkboxes
		for k, v in self.to_validate.items():
			# Amt from current Purchase Order is included in `self.ordered_amount` as doc is
			# in submitted status by the time the validation occurs
			if self.doc.doctype == "Purchase Order":
				self.get_ordered_amount(k)

			if self.doc.doctype == "Material Request":
				self.get_requested_amount(k)

			v["current_amount"] = sum([x.amount for x in v.get("items_to_process")])

		print(self.to_validate)
