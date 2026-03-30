import json

import frappe

from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from erpnext.tests.utils import ERPNextTestSuite


class TestTaxesAndTotals(ERPNextTestSuite):
	def setUp(self):
		self.doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer",
				"company": "_Test Company",
				"currency": "INR",
				"conversion_rate": 1,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 100,
						"income_account": "Sales - _TC",
						"expense_account": "Cost of Goods Sold - _TC",
						"cost_center": "_Test Cost Center - _TC",
					}
				],
				"taxes": [],
			}
		)

	def test_item_wise_tax_detail(self):
		# Test On Net Total
		self.doc.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": "_Test Account VAT - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "VAT",
				"rate": 10,
			},
		)

		# Test On Previous Row Amount
		self.doc.append(
			"taxes",
			{
				"charge_type": "On Previous Row Amount",
				"account_head": "_Test Account Service Tax - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Service Tax",
				"rate": 14,
				"row_id": 1,
			},
		)

		# Test On Previous Row Total
		self.doc.append(
			"taxes",
			{
				"charge_type": "On Previous Row Total",
				"account_head": "_Test Account Customs Duty - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Customs Duty",
				"rate": 5,
				"row_id": 2,
			},
		)

		# Test On Item Quantity
		self.doc.append(
			"taxes",
			{
				"charge_type": "On Item Quantity",
				"account_head": "_Test Account Shipping Charges - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"description": "Shipping",
				"rate": 50,
			},
		)
		self.doc.save()

		expected_values = [
			{
				"item_row": self.doc.items[0].name,
				"tax_row": self.doc.taxes[0].name,
				"rate": 10.0,
				"amount": 10.0,
				"taxable_amount": 100.0,
			},
			{
				"item_row": self.doc.items[0].name,
				"tax_row": self.doc.taxes[1].name,
				"rate": 14.0,
				"amount": 1.4,
				"taxable_amount": 10.0,
			},
			{
				"item_row": self.doc.items[0].name,
				"tax_row": self.doc.taxes[2].name,
				"rate": 5.0,
				"amount": 5.57,
				"taxable_amount": 111.4,
			},
			{
				"item_row": self.doc.items[0].name,
				"tax_row": self.doc.taxes[3].name,
				"rate": 50.0,
				"amount": 50.0,
				"taxable_amount": 0.0,
			},
		]

		actual_values = [
			{
				"item_row": row.item_row,
				"tax_row": row.tax_row,
				"rate": row.rate,
				"amount": row.amount,
				"taxable_amount": row.taxable_amount,
			}
			for row in self.doc.item_wise_tax_details
		]

		self.assertEqual(actual_values, expected_values)

	def test_item_wise_tax_detail_with_multi_currency(self):
		"""
		For multi-item, multi-currency invoices, item-wise tax breakup should
		still reconcile with base tax totals.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer",
				"company": "_Test Company",
				"currency": "USD",
				"debit_to": "_Test Receivable USD - _TC",
				"conversion_rate": 129.99,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 47.41,
						"income_account": "Sales - _TC",
						"expense_account": "Cost of Goods Sold - _TC",
						"cost_center": "_Test Cost Center - _TC",
					},
					{
						"item_code": "_Test Item 2",
						"qty": 2,
						"rate": 33.33,
						"income_account": "Sales - _TC",
						"expense_account": "Cost of Goods Sold - _TC",
						"cost_center": "_Test Cost Center - _TC",
					},
				],
				"taxes": [
					{
						"charge_type": "On Net Total",
						"account_head": "_Test Account VAT - _TC",
						"cost_center": "_Test Cost Center - _TC",
						"description": "VAT",
						"rate": 16,
					},
					{
						"charge_type": "On Previous Row Amount",
						"account_head": "_Test Account Service Tax - _TC",
						"cost_center": "_Test Cost Center - _TC",
						"description": "Service Tax",
						"rate": 10,
						"row_id": 1,
					},
				],
			}
		)
		doc.save()

		details_by_tax = {}
		for detail in doc.item_wise_tax_details:
			bucket = details_by_tax.setdefault(detail.tax_row, {"amount": 0.0})
			bucket["amount"] += detail.amount

		for tax in doc.taxes:
			self.assertEqual(details_by_tax[tax.name]["amount"], tax.base_tax_amount_after_discount_amount)

	def test_item_wise_tax_detail_with_multi_currency_with_single_item(self):
		"""
		When the tax amount (in transaction currency) has more decimals than
		the field precision, rounding must happen *before* multiplying by
		conversion_rate — the same order used by _set_in_company_currency.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"customer": "_Test Customer",
				"company": "_Test Company",
				"currency": "USD",
				"debit_to": "_Test Receivable USD - _TC",
				"conversion_rate": 129.99,
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": 47.41,
						"income_account": "Sales - _TC",
						"expense_account": "Cost of Goods Sold - _TC",
						"cost_center": "_Test Cost Center - _TC",
					}
				],
				"taxes": [
					{
						"charge_type": "On Net Total",
						"account_head": "_Test Account VAT - _TC",
						"cost_center": "_Test Cost Center - _TC",
						"description": "VAT",
						"rate": 16,
					},
				],
			}
		)
		doc.save()

		tax = doc.taxes[0]
		detail = doc.item_wise_tax_details[0]
		self.assertEqual(detail.amount, tax.base_tax_amount_after_discount_amount)
