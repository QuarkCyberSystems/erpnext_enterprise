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

	def get_active_budgets(self):
		self.active_keys = set()
		self.get_budget_records()
		for x in self.budgets:
			budget_against = frappe.scrub(x.budget_against)
			dimension = x.get(budget_against)
			self.active_keys = self.active_keys | set(
				[(budget_against, dimension, acc.account) for acc in x.accounts]
			)

	def generate_doc_dimension_keys(self):
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

	def validate(self):
		self.get_active_budgets()
		self.generate_doc_dimension_keys()

		print(self.active_keys)
		print(self.item_dimension_keys)
		print(self.active_keys & self.item_dimension_keys)
