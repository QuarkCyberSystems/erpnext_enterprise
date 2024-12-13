import frappe

# from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_dimensions
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

	def get_budget_records(self):
		self.budgets = []
		for x in frappe.db.get_all(
			"Budget", {"fiscal_year": self.fiscal_year, "docstatus": 1, "company": self.company}
		):
			self.budgets.append(frappe.get_doc("Budget", x.name))

	def generate_active_budget_keys(self):
		"""
		key structure - (dimension_type, dimension, GL account)
		"""
		self.active_keys = set()
		self.get_budget_records()
		for x in self.budgets:
			budget_against = frappe.scrub(x.budget_against)
			dimension = x.get(budget_against)
			self.active_keys = self.active_keys | set(
				[(budget_against, dimension, acc.account) for acc in x.accounts]
			)

	def generate_doc_dimension_keys(self):
		"""
		key structure - (dimension_type, dimension, GL account)
		"""
		keys = []
		for itm in self.doc.items:
			keys.extend(
				[
					(dim.get("fieldname"), itm.get(dim.get("fieldname")), itm.expense_account)
					for dim in self.dimensions
					if itm.get(dim.get("fieldname"))
				]
			)
		self.item_dimension_keys = set(keys)

	def build_processing_dictionary(self):
		self.budget_map = frappe._dict()

		for x in self.budgets:
			budget_against = frappe.scrub(x.budget_against)
			dimension = x.get(budget_against)
			for acc in x.accounts:
				key = (budget_against, dimension, acc.account)
				if key in self.overlap:
					self.budget_map[key] = frappe._dict(
						{"budget_amount": acc.budget_amount, "items_to_process": []}
					)

		for itm in self.doc.items:
			for dim in self.dimensions:
				if itm.get(dim.get("fieldname")):
					key = (dim.get("fieldname"), itm.get(dim.get("fieldname")), itm.expense_account)

					if key in self.overlap:
						self.budget_map[key]["items_to_process"].append(itm)

	def validate(self):
		self.generate_active_budget_keys()
		self.generate_doc_dimension_keys()

		self.overlap = self.active_keys & self.item_dimension_keys
		self.build_processing_dictionary()
		self.validate_for_overbooking()

	def get_booked_amount(self):
		pass

	def validate_for_overbooking(self):
		# Need to fetch historical amount and add them to the current document
		for k, v in self.budget_map.items():
			current_amount = sum([x.amount for x in v.items_to_process])
			self.budget_map[k]["current_amount"] = current_amount
			print((k, v.get("budget_amount"), current_amount))
