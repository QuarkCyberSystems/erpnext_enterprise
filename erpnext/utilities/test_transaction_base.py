import frappe
from frappe import qb
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, today

from erpnext.accounts.test.accounts_mixin import AccountsTestMixin


class TestAccountsController(AccountsTestMixin, IntegrationTestCase):
	def setUp(self):
		self.create_company()
		self.create_customer()
		self.create_item()
		self.create_usd_receivable_account()
		self.create_price_list()
		self.clear_old_entries()

	def tearDown(self):
		frappe.db.rollback()

	def test_01_basic_item_details(self):
		# set Item Price
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": self.item,
				"price_list": self.price_list,
				"price_list_rate": 90,
				"selling": True,
				"rate": 90,
				"valid_from": today(),
			}
		).insert()

		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"debit_to": self.debit_to,
				"posting_date": today(),
				"cost_center": self.cost_center,
				"conversion_rate": 1,
				"selling_price_list": self.price_list,
			}
		)
		itm = si.append("items")
		itm.item_code = self.item
		si.process_item_selection(si.items[0].name)
		self.assertEqual(itm.rate, 90)
