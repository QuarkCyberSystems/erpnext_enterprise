from collections import OrderedDict

import frappe
from frappe import qb

from erpnext.accounts.utils import get_fiscal_year


class BudgetValidation:
	def __init__(self, doc: object):
		self.doc = doc
		self.company = doc.get("company")
		self.doc_date = (
			doc.get("transaction_date") if doc.get("doctype") == "Purchase Order" else doc.get("posting_date")
		)
		self.fiscal_year = get_fiscal_year(self.doc_date)[0]
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

	def build_to_validate_map(self):
		self.overlap = self.budget_keys & self.doc_or_item_keys
		self.to_validate = OrderedDict()

		for key in self.overlap:
			self.to_validate[key] = OrderedDict(
				{
					"budget_amount": self.budget_map[key].budget_amount,
					"items_to_process": self.doc_or_item_map[key],
				}
			)

	def validate(self):
		self.build_budget_keys_and_map()
		self.build_doc_or_item_keys_and_map()
		self.build_to_validate_map()
		self.validate_for_overbooking()

	def validate_for_overbooking(self):
		# TODO: Need to fetch historical amount and add them to the current document
		# TODO: handle applicable checkboxes
		for k, v in self.to_validate.items():
			current_amount = sum([x.amount for x in v.get("items_to_process")])
			print((k, v.get("budget_amount"), current_amount))
