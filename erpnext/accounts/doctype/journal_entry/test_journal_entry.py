# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import flt, nowdate

from erpnext.accounts.doctype.account.test_account import get_inventory_account
from erpnext.accounts.doctype.journal_entry.journal_entry import StockAccountInvalidTransaction
from erpnext.exceptions import InvalidAccountCurrency
from erpnext.selling.doctype.customer.test_customer import make_customer, set_credit_limit
from erpnext.tests.utils import ERPNextTestSuite


class TestJournalEntry(ERPNextTestSuite):
	def setUp(self):
		self.load_test_records("Journal Entry")

	@ERPNextTestSuite.change_settings("Accounts Settings", {"unlink_payment_on_cancellation_of_invoice": 1})
	def test_journal_entry_with_against_jv(self):
		jv_invoice = frappe.copy_doc(self.globalTestRecords["Journal Entry"][2])
		base_jv = frappe.copy_doc(self.globalTestRecords["Journal Entry"][0])
		self.jv_against_voucher_testcase(base_jv, jv_invoice)

	def test_jv_against_sales_order(self):
		from erpnext.selling.doctype.sales_order.test_sales_order import make_sales_order

		sales_order = make_sales_order(do_not_save=True)
		base_jv = frappe.copy_doc(self.globalTestRecords["Journal Entry"][0])
		self.jv_against_voucher_testcase(base_jv, sales_order)

	def test_jv_against_purchase_order(self):
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

		purchase_order = create_purchase_order(do_not_save=True)
		base_jv = frappe.copy_doc(self.globalTestRecords["Journal Entry"][1])
		self.jv_against_voucher_testcase(base_jv, purchase_order)

	def jv_against_voucher_testcase(self, base_jv, test_voucher):
		dr_or_cr = "credit" if test_voucher.doctype in ["Sales Order", "Journal Entry"] else "debit"

		test_voucher.insert()
		test_voucher.submit()

		if test_voucher.doctype == "Journal Entry":
			self.assertTrue(
				frappe.db.sql(
					"""select name from `tabJournal Entry Account`
				where account = %s and docstatus = 1 and parent = %s""",
					("Debtors - _TC", test_voucher.name),
				)
			)

		self.assertFalse(
			frappe.db.sql(
				"""select name from `tabJournal Entry Account`
			where reference_type = %s and reference_name = %s""",
				(test_voucher.doctype, test_voucher.name),
			)
		)

		base_jv.get("accounts")[0].is_advance = (
			"Yes" if (test_voucher.doctype in ["Sales Order", "Purchase Order"]) else "No"
		)
		base_jv.get("accounts")[0].set("reference_type", test_voucher.doctype)
		base_jv.get("accounts")[0].set("reference_name", test_voucher.name)
		base_jv.insert()
		base_jv.submit()

		submitted_voucher = frappe.get_doc(test_voucher.doctype, test_voucher.name)

		self.assertTrue(
			frappe.db.sql(
				f"""select name from `tabJournal Entry Account`
			where reference_type = %s and reference_name = %s and {dr_or_cr}=400""",
				(submitted_voucher.doctype, submitted_voucher.name),
			)
		)

		if base_jv.get("accounts")[0].is_advance == "Yes":
			self.advance_paid_testcase(base_jv, submitted_voucher, dr_or_cr)
		self.cancel_against_voucher_testcase(submitted_voucher)

	def advance_paid_testcase(self, base_jv, test_voucher, dr_or_cr):
		# Test advance paid field
		advance_paid = frappe.db.sql(
			"""select advance_paid from `tab{}`
					where name={}""".format(test_voucher.doctype, "%s"),
			(test_voucher.name),
		)
		payment_against_order = base_jv.get("accounts")[0].get(dr_or_cr)

		self.assertTrue(flt(advance_paid[0][0]) == flt(payment_against_order))

	def cancel_against_voucher_testcase(self, test_voucher):
		if test_voucher.doctype == "Journal Entry":
			# if test_voucher is a Journal Entry, test cancellation of test_voucher
			test_voucher.cancel()
			self.assertFalse(
				frappe.db.sql(
					"""select name from `tabJournal Entry Account`
				where reference_type='Journal Entry' and reference_name=%s""",
					test_voucher.name,
				)
			)

		elif test_voucher.doctype in ["Sales Order", "Purchase Order"]:
			# if test_voucher is a Sales Order/Purchase Order, test error on cancellation of test_voucher
			frappe.db.set_single_value(
				"Accounts Settings", "unlink_advance_payment_on_cancelation_of_order", 0
			)
			submitted_voucher = frappe.get_doc(test_voucher.doctype, test_voucher.name)
			self.assertRaises(frappe.LinkExistsError, submitted_voucher.cancel)

	def test_jv_against_stock_account(self):
		company = "_Test Company with perpetual inventory"
		stock_account = get_inventory_account(company)

		from erpnext.accounts.utils import get_stock_and_account_balance

		account_bal, stock_bal, warehouse_list = get_stock_and_account_balance(
			stock_account, nowdate(), company
		)
		diff = flt(account_bal) - flt(stock_bal)

		if not diff:
			diff = 100

		jv = frappe.new_doc("Journal Entry")
		jv.company = company
		jv.posting_date = nowdate()
		jv.append(
			"accounts",
			{
				"account": stock_account,
				"cost_center": "Main - TCP1",
				"debit_in_account_currency": 0 if diff > 0 else abs(diff),
				"credit_in_account_currency": diff if diff > 0 else 0,
			},
		)

		jv.append(
			"accounts",
			{
				"account": "Stock Adjustment - TCP1",
				"cost_center": "Main - TCP1",
				"debit_in_account_currency": diff if diff > 0 else 0,
				"credit_in_account_currency": 0 if diff > 0 else abs(diff),
			},
		)

		if account_bal == stock_bal:
			self.assertRaises(StockAccountInvalidTransaction, jv.save)
		else:
			jv.submit()
			jv.cancel()

	def test_multi_currency(self):
		jv = make_journal_entry("_Test Bank USD - _TC", "_Test Bank - _TC", 100, exchange_rate=50, save=False)

		jv.get("accounts")[1].credit_in_account_currency = 5000
		jv.submit()

		self.voucher_no = jv.name

		self.fields = [
			"account",
			"account_currency",
			"debit",
			"debit_in_account_currency",
			"credit",
			"credit_in_account_currency",
		]

		self.expected_gle = [
			{
				"account": "_Test Bank - _TC",
				"account_currency": "INR",
				"debit": 0,
				"debit_in_account_currency": 0,
				"credit": 5000,
				"credit_in_account_currency": 5000,
			},
			{
				"account": "_Test Bank USD - _TC",
				"account_currency": "USD",
				"debit": 5000,
				"debit_in_account_currency": 100,
				"credit": 0,
				"credit_in_account_currency": 0,
			},
		]

		self.check_gl_entries()

		# cancel
		jv.cancel()

		gle = frappe.db.sql(
			"""select name from `tabGL Entry`
			where voucher_type='Sales Invoice' and voucher_no=%s""",
			jv.name,
		)

		self.assertFalse(gle)

	def test_reverse_journal_entry(self):
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		jv = make_journal_entry("_Test Bank USD - _TC", "Sales - _TC", 100, exchange_rate=50, save=False)

		jv.get("accounts")[1].credit_in_account_currency = 5000
		jv.get("accounts")[1].exchange_rate = 1
		jv.submit()

		rjv = make_reverse_journal_entry(jv.name)
		rjv.posting_date = nowdate()
		rjv.submit()

		self.voucher_no = rjv.name

		self.fields = [
			"account",
			"account_currency",
			"debit",
			"credit",
			"debit_in_account_currency",
			"credit_in_account_currency",
		]

		self.expected_gle = [
			{
				"account": "_Test Bank USD - _TC",
				"account_currency": "USD",
				"debit": 0,
				"debit_in_account_currency": 0,
				"credit": 5000,
				"credit_in_account_currency": 100,
			},
			{
				"account": "Sales - _TC",
				"account_currency": "INR",
				"debit": 5000,
				"debit_in_account_currency": 5000,
				"credit": 0,
				"credit_in_account_currency": 0,
			},
		]

		self.check_gl_entries()

	def test_disallow_change_in_account_currency_for_a_party(self):
		# create jv in USD
		jv = make_journal_entry("_Test Bank USD - _TC", "_Test Receivable USD - _TC", 100, save=False)

		jv.accounts[1].update({"party_type": "Customer", "party": "_Test Customer USD"})

		jv.submit()

		# create jv in USD, but account currency in INR
		jv = make_journal_entry("_Test Bank - _TC", "Debtors - _TC", 100, save=False)

		jv.accounts[1].update({"party_type": "Customer", "party": "_Test Customer USD"})

		self.assertRaises(InvalidAccountCurrency, jv.submit)

		# back in USD
		jv = make_journal_entry("_Test Bank USD - _TC", "_Test Receivable USD - _TC", 100, save=False)

		jv.accounts[1].update({"party_type": "Customer", "party": "_Test Customer USD"})

		jv.submit()

	def test_inter_company_jv(self):
		jv = make_journal_entry(
			"Sales Expenses - _TC",
			"Buildings - _TC",
			100,
			posting_date=nowdate(),
			cost_center="Main - _TC",
			save=False,
		)
		jv.voucher_type = "Inter Company Journal Entry"
		jv.multi_currency = 0
		jv.insert()
		jv.submit()

		jv1 = make_journal_entry(
			"Sales Expenses - _TC1",
			"Buildings - _TC1",
			100,
			posting_date=nowdate(),
			cost_center="Main - _TC1",
			save=False,
		)
		jv1.inter_company_journal_entry_reference = jv.name
		jv1.company = "_Test Company 1"
		jv1.voucher_type = "Inter Company Journal Entry"
		jv1.multi_currency = 0
		jv1.insert()
		jv1.submit()

		jv.reload()

		self.assertEqual(jv.inter_company_journal_entry_reference, jv1.name)
		self.assertEqual(jv1.inter_company_journal_entry_reference, jv.name)

		jv.cancel()
		jv1.reload()
		jv.reload()

		self.assertEqual(jv.inter_company_journal_entry_reference, "")
		self.assertEqual(jv1.inter_company_journal_entry_reference, "")

	def test_jv_with_cost_centre(self):
		from erpnext.accounts.doctype.cost_center.test_cost_center import create_cost_center

		cost_center = "_Test Cost Center for BS Account - _TC"
		create_cost_center(cost_center_name="_Test Cost Center for BS Account", company="_Test Company")
		jv = make_journal_entry(
			"_Test Cash - _TC", "_Test Bank - _TC", 100, cost_center=cost_center, save=False
		)
		jv.voucher_type = "Bank Entry"
		jv.multi_currency = 0
		jv.cheque_no = "112233"
		jv.cheque_date = nowdate()
		jv.insert()
		jv.submit()

		self.voucher_no = jv.name

		self.fields = [
			"account",
			"cost_center",
		]

		self.expected_gle = [
			{
				"account": "_Test Bank - _TC",
				"cost_center": cost_center,
			},
			{
				"account": "_Test Cash - _TC",
				"cost_center": cost_center,
			},
		]

		self.check_gl_entries()

	def test_jv_with_project(self):
		from erpnext.projects.doctype.project.test_project import make_project

		if not frappe.db.exists("Project", {"project_name": "Journal Entry Project"}):
			project = make_project(
				{
					"project_name": "Journal Entry Project",
					"project_template_name": "Test Project Template",
					"start_date": "2020-01-01",
				}
			)
			project_name = project.name
		else:
			project_name = frappe.get_value("Project", {"project_name": "_Test Project"})

		jv = make_journal_entry("_Test Cash - _TC", "_Test Bank - _TC", 100, save=False)
		for d in jv.accounts:
			d.project = project_name
		jv.voucher_type = "Bank Entry"
		jv.multi_currency = 0
		jv.cheque_no = "112233"
		jv.cheque_date = nowdate()
		jv.insert()
		jv.submit()

		self.voucher_no = jv.name

		self.fields = ["account", "project"]

		self.expected_gle = [
			{
				"account": "_Test Bank - _TC",
				"project": project_name,
			},
			{
				"account": "_Test Cash - _TC",
				"project": project_name,
			},
		]

		self.check_gl_entries()

	def test_jv_account_and_party_balance_with_cost_centre(self):
		from erpnext.accounts.doctype.cost_center.test_cost_center import create_cost_center
		from erpnext.accounts.utils import get_balance_on

		cost_center = "_Test Cost Center for BS Account - _TC"
		create_cost_center(cost_center_name="_Test Cost Center for BS Account", company="_Test Company")
		jv = make_journal_entry(
			"_Test Cash - _TC", "_Test Bank - _TC", 100, cost_center=cost_center, save=False
		)
		account_balance = get_balance_on(account="_Test Bank - _TC", cost_center=cost_center)
		jv.voucher_type = "Bank Entry"
		jv.multi_currency = 0
		jv.cheque_no = "112233"
		jv.cheque_date = nowdate()
		jv.insert()
		jv.submit()

		expected_account_balance = account_balance - 100
		account_balance = get_balance_on(account="_Test Bank - _TC", cost_center=cost_center)
		self.assertEqual(expected_account_balance, account_balance)

	def test_repost_accounting_entries(self):
		from erpnext.accounts.doctype.cost_center.test_cost_center import create_cost_center

		# Configure Repost Accounting Ledger for JVs
		settings = frappe.get_doc("Accounts Settings")
		if "Journal Entry" not in [x.document_type for x in settings.repost_allowed_types]:
			settings.append("repost_allowed_types", {"document_type": "Journal Entry"})
		settings.save()

		# Create JV with defaut cost center - _Test Cost Center
		jv = make_journal_entry("_Test Cash - _TC", "_Test Bank - _TC", 100, save=False)
		jv.multi_currency = 0
		jv.submit()

		# Check GL entries before reposting
		self.voucher_no = jv.name

		self.fields = [
			"account",
			"debit_in_account_currency",
			"credit_in_account_currency",
			"cost_center",
		]

		self.expected_gle = [
			{
				"account": "_Test Bank - _TC",
				"debit_in_account_currency": 0,
				"credit_in_account_currency": 100,
				"cost_center": "_Test Cost Center - _TC",
			},
			{
				"account": "_Test Cash - _TC",
				"debit_in_account_currency": 100,
				"credit_in_account_currency": 0,
				"cost_center": "_Test Cost Center - _TC",
			},
		]

		self.check_gl_entries()

		# Change cost center for bank account - _Test Cost Center for BS Account
		create_cost_center(cost_center_name="_Test Cost Center for BS Account", company="_Test Company")
		jv.accounts[1].cost_center = "_Test Cost Center for BS Account - _TC"
		# Ledger reposted implicitly upon 'Update After Submit'
		jv.save()

		# Check GL entries after reposting
		jv.load_from_db()
		self.expected_gle[0]["cost_center"] = "_Test Cost Center for BS Account - _TC"
		self.check_gl_entries()

	def check_gl_entries(self):
		gl = frappe.qb.DocType("GL Entry")
		query = frappe.qb.from_(gl)
		for field in self.fields:
			query = query.select(gl[field])

		query = query.where(
			(gl.voucher_type == "Journal Entry") & (gl.voucher_no == self.voucher_no) & (gl.is_cancelled == 0)
		).orderby(gl.account)

		gl_entries = query.run(as_dict=True)

		for i in range(len(self.expected_gle)):
			for field in self.fields:
				self.assertEqual(self.expected_gle[i][field], gl_entries[i][field])

	def test_negative_debit_and_credit_with_same_account_head(self):
		from erpnext.accounts.general_ledger import process_gl_map

		# Create JV with defaut cost center - _Test Cost Center
		frappe.db.set_single_value("Accounts Settings", "merge_similar_account_heads", 0)

		jv = make_journal_entry("_Test Bank - _TC", "_Test Bank - _TC", 100 * -1, save=True)
		jv.append(
			"accounts",
			{
				"account": "_Test Cash - _TC",
				"debit": 100 * -1,
				"credit": 100 * -1,
				"debit_in_account_currency": 100 * -1,
				"credit_in_account_currency": 100 * -1,
				"exchange_rate": 1,
			},
		)
		jv.flags.ignore_validate = True
		jv.save()

		self.assertEqual(len(jv.accounts), 3)

		gl_map = jv.build_gl_map()

		for row in gl_map:
			if row.account == "_Test Cash - _TC":
				self.assertEqual(row.debit_in_account_currency, 100 * -1)
				self.assertEqual(row.credit_in_account_currency, 100 * -1)

		gl_map = process_gl_map(gl_map, False)

		for row in gl_map:
			if row.account == "_Test Cash - _TC":
				self.assertEqual(row.debit_in_account_currency, 100)
				self.assertEqual(row.credit_in_account_currency, 100)

	def test_toggle_debit_credit_if_negative(self):
		from erpnext.accounts.general_ledger import process_gl_map

		# Create JV with defaut cost center - _Test Cost Center
		frappe.db.set_single_value("Accounts Settings", "merge_similar_account_heads", 0)

		jv = frappe.new_doc("Journal Entry")
		jv.posting_date = nowdate()
		jv.company = "_Test Company"
		jv.remark = "test"
		jv.extend(
			"accounts",
			[
				{
					"account": "_Test Cash - _TC",
					"debit": 100 * -1,
					"debit_in_account_currency": 100 * -1,
					"exchange_rate": 1,
				},
				{
					"account": "_Test Bank - _TC",
					"credit": 100 * -1,
					"credit_in_account_currency": 100 * -1,
					"exchange_rate": 1,
				},
			],
		)

		jv.flags.ignore_validate = True
		jv.save()

		self.assertEqual(len(jv.accounts), 2)

		gl_map = jv.build_gl_map()

		for row in gl_map:
			if row.account == "_Test Cash - _TC":
				self.assertEqual(row.debit, 100 * -1)
				self.assertEqual(row.debit_in_account_currency, 100 * -1)
				self.assertEqual(row.debit_in_transaction_currency, 100 * -1)

		gl_map = process_gl_map(gl_map, False)

		for row in gl_map:
			if row.account == "_Test Cash - _TC":
				self.assertEqual(row.credit, 100)
				self.assertEqual(row.credit_in_account_currency, 100)
				self.assertEqual(row.credit_in_transaction_currency, 100)

	def test_transaction_exchange_rate_on_journals(self):
		jv = make_journal_entry("_Test Bank - _TC", "_Test Receivable USD - _TC", 100, save=False)
		jv.accounts[0].update({"debit_in_account_currency": 8500, "exchange_rate": 1})
		jv.accounts[1].update({"party_type": "Customer", "party": "_Test Customer USD", "exchange_rate": 85})
		jv.submit()
		actual = frappe.db.get_all(
			"GL Entry",
			filters={"voucher_no": jv.name, "is_cancelled": 0},
			fields=["account", "transaction_exchange_rate"],
			order_by="account",
		)
		expected = [
			{"account": "_Test Bank - _TC", "transaction_exchange_rate": 85.0},
			{"account": "_Test Receivable USD - _TC", "transaction_exchange_rate": 85.0},
		]
		self.assertEqual(expected, actual)

	def test_pay_to_recd_from(self):
		jv = make_journal_entry("_Test Cash - _TC", "_Test Bank - _TC", 100, save=False)
		jv.pay_to_recd_from = "_Test Receiver"
		jv.save()
		self.assertEqual(jv.pay_to_recd_from, "_Test Receiver")

		jv.pay_to_recd_from = "_Test Receiver 2"
		jv.save()
		jv.submit()

		self.assertEqual(jv.pay_to_recd_from, "_Test Receiver 2")

	def test_custom_remark(self):
		# When custom_remark is enabled, remark should not be auto-overwritten on save
		jv = make_journal_entry("_Test Cash - _TC", "_Test Bank - _TC", 100, save=False)
		jv.custom_remark = 1
		jv.remark = "My custom remark text"
		jv.insert()
		self.assertEqual(jv.remark, "My custom remark text")

	def test_credit_limit_for_customer(self):
		customer = make_customer("_Test New Customer")
		set_credit_limit("_Test New Customer", "_Test Company", 50)
		jv = make_journal_entry(account1="Debtors - _TC", account2="_Test Cash - _TC", amount=100, save=False)
		jv.accounts[0].party_type = "Customer"
		jv.accounts[0].party = customer
		jv.save()
		self.assertRaises(frappe.ValidationError, jv.submit)

	# ------------------------------------------------------------------
	# Reversal Journal Entry enhancements (WP GA-0001-01)
	# ------------------------------------------------------------------

	def _make_reversal(self, original):
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		reversal = make_reverse_journal_entry(original.name)
		reversal.posting_date = nowdate()
		reversal.insert()
		return reversal

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_two_way_linking_on_submit(self):
		# TC-001: submitting a reversal sets is_reversed + reversed_by on the
		# original and is_reversal on the reversal.
		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 500, submit=True
		)
		reversal = self._make_reversal(original)
		reversal.submit()

		original.reload()
		self.assertEqual(original.is_reversed, 1)
		self.assertEqual(original.reversed_by, reversal.name)
		self.assertEqual(reversal.is_reversal, 1)
		self.assertEqual(reversal.reversal_of, original.name)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_link_cleanup_on_cancel(self):
		# TC-002: cancelling a reversal under immutable-ledger OFF clears the
		# back-pointer on the original.
		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 600, submit=True
		)
		reversal = self._make_reversal(original)
		reversal.submit()
		reversal.cancel()

		original.reload()
		self.assertEqual(original.is_reversed, 0)
		self.assertIsNone(original.reversed_by)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_blocks_duplicate_draft(self):
		# TC-003: only one draft-or-submitted reversal may exist per original.
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 700, submit=True
		)
		first = self._make_reversal(original)
		self.assertTrue(first.name)

		self.assertRaises(
			frappe.ValidationError,
			make_reverse_journal_entry,
			original.name,
		)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_field_lock_bypass_blocked(self):
		# TC-004: backend rejects edits to fields copied from the original
		# (even when UI locking is bypassed via db_set).
		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 800, submit=True
		)
		reversal = self._make_reversal(original)
		reversal.db_set("cheque_no", "TAMPERED", update_modified=False)
		reversal.reload()
		self.assertRaises(frappe.ValidationError, reversal.save)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_total_mismatch_blocked(self):
		# TC-005: totals of the reversal must mirror the original's.
		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 900, submit=True
		)
		reversal = self._make_reversal(original)
		# Swap two rows via direct attribute changes so validate_reversal_*
		# sees mismatched totals while row-level locked-field checks pass.
		reversal.accounts[0].debit_in_account_currency = 100
		reversal.accounts[0].credit_in_account_currency = 0
		self.assertRaises(frappe.ValidationError, reversal.save)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_indicator_data_populated(self):
		# TC-006: the flags the dashboard indicator reads must be populated
		# after submit on both sides of the reversal pair.
		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 1000, submit=True
		)
		reversal = self._make_reversal(original)
		reversal.submit()

		original.reload()
		reversal.reload()
		self.assertEqual(original.is_reversed, 1)
		self.assertEqual(original.reversed_by, reversal.name)
		self.assertEqual(reversal.is_reversal, 1)
		self.assertEqual(reversal.reversal_of, original.name)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_of_reversal_blocked(self):
		# TC-007 (new, GAP-010): reversing a reversal entry is always blocked.
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 1100, submit=True
		)
		reversal = self._make_reversal(original)
		reversal.submit()

		self.assertRaises(
			frappe.ValidationError,
			make_reverse_journal_entry,
			reversal.name,
		)

	def test_reversal_cancel_blocked_under_immutable_ledger(self):
		# TC-008 (new, GAP-010): cancel of a reversal is blocked when
		# Immutable Ledger is enabled.
		frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 0)
		original = make_journal_entry(
			"_Test Bank - _TC", "_Test Cash - _TC", 1200, submit=True
		)
		reversal = self._make_reversal(original)
		reversal.submit()

		try:
			frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 1)
			self.assertRaises(frappe.ValidationError, reversal.cancel)
		finally:
			frappe.db.set_single_value("Accounts Settings", "enable_immutable_ledger", 0)

	@ERPNextTestSuite.change_settings("Accounts Settings", {"enable_immutable_ledger": 0})
	def test_reversal_cost_center_reresolution(self):
		# TC-009 (new, GAP-009): toggling respect_cost_center_allocation off
		# rewrites the reversal's row cost centers to the main ancestor so
		# GL-layer allocation fans out at the reversal posting date.
		from erpnext.accounts.doctype.cost_center.test_cost_center import create_cost_center

		company = "_Test Company"
		company_abbr = frappe.db.get_value("Company", company, "abbr")
		main_name = "_Test Reversal Main CC"
		leaf_name = "_Test Reversal Leaf CC"
		create_cost_center(cost_center_name=main_name, company=company)
		create_cost_center(cost_center_name=leaf_name, company=company)
		main_cc = f"{main_name} - {company_abbr}"
		leaf_cc = f"{leaf_name} - {company_abbr}"

		# Seed an allocation so _find_main_cost_center_for_leaf returns main_cc
		# when looking up leaf_cc.
		if not frappe.db.exists(
			"Cost Center Allocation",
			{"main_cost_center": main_cc, "docstatus": 1},
		):
			allocation = frappe.new_doc("Cost Center Allocation")
			allocation.main_cost_center = main_cc
			allocation.company = company
			allocation.valid_from = nowdate()
			allocation.append("allocation_percentages", {"cost_center": leaf_cc, "percentage": 100})
			try:
				allocation.insert()
				allocation.submit()
			except frappe.ValidationError:
				# Cost Center Allocation has strict rules (no existing GL
				# entries under main, no hierarchy overlap). Skip when the
				# fixture state forbids seeding.
				self.skipTest("Cost Center Allocation not permitted by fixture constraints")

		original = make_journal_entry(
			"_Test Bank - _TC",
			"_Test Cash - _TC",
			1300,
			cost_center=leaf_cc,
			submit=True,
		)
		reversal = self._make_reversal(original)
		self.assertEqual(reversal.accounts[0].cost_center, leaf_cc)

		reversal.respect_cost_center_allocation = 0
		reversal.save()
		reversal.reload()
		self.assertEqual(reversal.accounts[0].cost_center, main_cc)


class TestJournalEntryTemplateEnforcement(ERPNextTestSuite):
	"""GA-0001-04: JE Template enforcement and Auto Reversal inheritance."""

	@classmethod
	def _make_template(
		cls,
		title,
		voucher_type="Journal Entry",
		lock_on_apply=1,
		allow_additional_accounts=0,
		accounts=None,
		auto_reversal_kwargs=None,
	):
		if frappe.db.exists("Journal Entry Template", title):
			frappe.delete_doc("Journal Entry Template", title, force=1)
		tpl = frappe.new_doc("Journal Entry Template")
		tpl.template_title = title
		tpl.voucher_type = voucher_type
		tpl.company = "_Test Company"
		tpl.naming_series = "ACC-JV-.YYYY.-"
		tpl.lock_on_apply = lock_on_apply
		tpl.allow_additional_accounts = allow_additional_accounts
		for acc in accounts or [
			{"account": "_Test Cash - _TC"},
			{"account": "_Test Bank - _TC"},
		]:
			tpl.append("accounts", acc)
		if auto_reversal_kwargs:
			tpl.update(auto_reversal_kwargs)
		tpl.insert()
		return tpl

	def _make_je_from_template(self, tpl, amounts=None):
		"""Mirror what the client-side apply_template handler does, server-side."""
		amounts = amounts or [(100, 0), (0, 100)]
		je = frappe.new_doc("Journal Entry")
		je.posting_date = nowdate()
		je.company = tpl.company
		je.voucher_type = tpl.voucher_type
		je.naming_series = tpl.naming_series
		je.is_opening = tpl.is_opening
		je.multi_currency = tpl.multi_currency
		je.from_template = tpl.name
		je.template_applied = 1
		je.enable_auto_reversal = tpl.enable_auto_reversal
		je.auto_reverse_on = tpl.auto_reverse_on
		je.auto_reverse_date = tpl.auto_reverse_date
		je.reversal_exchange_rate_type = tpl.reversal_exchange_rate_type
		je.reversal_tax_mode = tpl.reversal_tax_mode
		je.reversal_cost_center_mode = tpl.reversal_cost_center_mode
		je.auto_submit_reversal = tpl.auto_submit_reversal
		for tpl_row, (debit, credit) in zip(tpl.accounts, amounts, strict=False):
			je.append(
				"accounts",
				{
					"account": tpl_row.account,
					"party_type": tpl_row.party_type,
					"party": tpl_row.party,
					"cost_center": tpl_row.cost_center or "_Test Cost Center - _TC",
					"project": tpl_row.project,
					"user_remark": tpl_row.user_remark,
					"debit_in_account_currency": debit,
					"credit_in_account_currency": credit,
					"from_template": 1,
				},
			)
		return je

	# TC-006 - Server-side parity check rejects missing template account
	def test_tc006_server_validation_blocks_missing_template_account(self):
		tpl = self._make_template("_Test JE Tpl TC006")
		je = self._make_je_from_template(tpl)
		je.accounts.pop()  # remove a template-derived row
		self.assertRaises(frappe.ValidationError, je.insert)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-006b - Replacing a template account with a different one is also rejected
	def test_tc006_server_validation_blocks_swapped_account(self):
		tpl = self._make_template("_Test JE Tpl TC006b")
		je = self._make_je_from_template(tpl)
		je.accounts[0].account = "_Test Receivable - _TC"
		self.assertRaises(frappe.ValidationError, je.insert)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-004 - allow_additional_accounts=0 blocks user-added rows on the server
	def test_tc004_server_blocks_extra_rows_when_disallowed(self):
		tpl = self._make_template(
			"_Test JE Tpl TC004", allow_additional_accounts=0
		)
		je = self._make_je_from_template(tpl)
		je.append(
			"accounts",
			{
				"account": "_Test Receivable - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"debit_in_account_currency": 0,
				"credit_in_account_currency": 0,
				"from_template": 0,
			},
		)
		self.assertRaises(frappe.ValidationError, je.insert)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-003 - allow_additional_accounts=1 lets the user add a non-template row
	def test_tc003_server_allows_extra_rows_when_permitted(self):
		tpl = self._make_template(
			"_Test JE Tpl TC003", allow_additional_accounts=1
		)
		je = self._make_je_from_template(tpl)
		je.append(
			"accounts",
			{
				"account": "_Test Receivable - _TC",
				"cost_center": "_Test Cost Center - _TC",
				"debit_in_account_currency": 50,
				"credit_in_account_currency": 0,
				"from_template": 0,
			},
		)
		# Adjust totals so the JE balances
		je.accounts[1].credit_in_account_currency = 150
		je.insert()
		self.assertEqual(je.template_applied, 1)
		non_tpl_rows = [r for r in je.accounts if not r.from_template]
		self.assertEqual(len(non_tpl_rows), 1)
		frappe.delete_doc("Journal Entry", je.name, force=1)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-005 - before_save clears template_applied + row from_template when from_template cleared
	def test_tc005_clearing_from_template_resets_state(self):
		tpl = self._make_template("_Test JE Tpl TC005")
		je = self._make_je_from_template(tpl)
		je.insert()
		je.from_template = None
		je.save()
		self.assertEqual(je.template_applied, 0)
		for row in je.accounts:
			self.assertEqual(row.from_template, 0)
		frappe.delete_doc("Journal Entry", je.name, force=1)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-007 - editing amounts on template rows is allowed
	def test_tc007_amount_edits_allowed_on_template_rows(self):
		tpl = self._make_template("_Test JE Tpl TC007")
		je = self._make_je_from_template(tpl)
		je.insert()
		je.accounts[0].debit_in_account_currency = 250
		je.accounts[1].credit_in_account_currency = 250
		je.save()
		self.assertEqual(flt(je.accounts[0].debit_in_account_currency), 250)
		frappe.delete_doc("Journal Entry", je.name, force=1)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-010 - Template's seven Auto Reversal fields land on JE
	def test_tc010_auto_reversal_fields_inherit_from_template(self):
		tpl = self._make_template(
			"_Test JE Tpl TC010",
			auto_reversal_kwargs={
				"enable_auto_reversal": 1,
				"auto_reverse_on": "Specific Date",
				"auto_reverse_date": nowdate(),
				"reversal_exchange_rate_type": "Current Rate",
				"reversal_tax_mode": "Recalculate for Posting Date",
				"reversal_cost_center_mode": "Apply Current Allocation",
				"auto_submit_reversal": 1,
			},
		)
		je = self._make_je_from_template(tpl)
		je.insert()
		self.assertEqual(je.enable_auto_reversal, 1)
		self.assertEqual(je.auto_reverse_on, "Specific Date")
		self.assertEqual(je.reversal_exchange_rate_type, "Current Rate")
		self.assertEqual(je.reversal_tax_mode, "Recalculate for Posting Date")
		self.assertEqual(je.reversal_cost_center_mode, "Apply Current Allocation")
		self.assertEqual(je.auto_submit_reversal, 1)
		frappe.delete_doc("Journal Entry", je.name, force=1)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-012 - Auto Repeat skipped + error logged when GA-0001-05+06 not deployed
	def test_tc012_auto_reversal_skipped_when_repeat_type_missing(self):
		if frappe.get_meta("Auto Repeat").has_field("repeat_type"):
			self.skipTest("GA-0001-05+06 deployed; capability-detected branch not exercised")
		tpl = self._make_template(
			"_Test JE Tpl TC012",
			auto_reversal_kwargs={
				"enable_auto_reversal": 1,
				"auto_reverse_on": "First Day of Next Month",
			},
		)
		je = self._make_je_from_template(
			tpl, amounts=[(500, 0), (0, 500)]
		)
		je.insert()
		je.submit()
		# JE should still submit cleanly; no Auto Repeat created
		ar_count = frappe.db.count(
			"Auto Repeat",
			{"reference_doctype": "Journal Entry", "reference_document": je.name},
		)
		self.assertEqual(ar_count, 0)
		self.assertEqual(je.docstatus, 1)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# TC-014 - Re-applying same template re-marks rows cleanly (idempotent reseed)
	def test_tc014_reapply_template_resets_state(self):
		tpl = self._make_template("_Test JE Tpl TC014")
		je = self._make_je_from_template(tpl)
		je.insert()
		# Simulate clear + reapply on existing JE
		je.from_template = None
		je.save()
		self.assertEqual(je.template_applied, 0)
		# Reapply by a fresh server-side seed
		fresh = self._make_je_from_template(tpl, amounts=[(75, 0), (0, 75)])
		fresh.insert()
		self.assertEqual(fresh.template_applied, 1)
		self.assertEqual(len([r for r in fresh.accounts if r.from_template]), 2)
		frappe.delete_doc("Journal Entry", je.name, force=1)
		frappe.delete_doc("Journal Entry", fresh.name, force=1)
		frappe.delete_doc("Journal Entry Template", tpl.name, force=1)

	# ──────────────────────────────────────────────────────────────────────
	# WP GA-0001-05+06 — Auto Repeat (Reversal) integration tests
	# Each test self-skips when Auto Repeat is missing the repeat_type field
	# (i.e., when the Frappe-side WP isn't deployed yet) so the file remains
	# safe to run on any version-16 site.
	# ──────────────────────────────────────────────────────────────────────

	def _auto_repeat_reversal_available(self):
		return frappe.get_meta("Auto Repeat").has_field("repeat_type")

	def _make_submitted_jv(self, amount=100, **kwargs):
		"""Helper: a submitted JE suitable as a reversal source."""
		jv = make_journal_entry("_Test Cash - _TC", "Sales - _TC", amount, save=False, **kwargs)
		jv.submit()
		return jv

	def test_auto_repeat_reversal_blocks_manual_reversal(self):
		"""TC-012: While an active Auto Repeat (Reversal) is linked, manual
		make_reverse_journal_entry must throw."""
		if not self._auto_repeat_reversal_available():
			self.skipTest("Auto Repeat does not expose repeat_type — Frappe-side WP not deployed")
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		jv = self._make_submitted_jv()
		# Simulate the link an active Auto Repeat (Reversal) would set on insert.
		ar = frappe.new_doc("Auto Repeat")
		ar.update(
			{
				"reference_doctype": "Journal Entry",
				"reference_document": jv.name,
				"repeat_type": "Reversal",
				"reverse_on_next_month": 1,
				"start_date": nowdate(),
				"frequency": "",
			}
		)
		ar.flags.ignore_permissions = True
		ar.insert()
		ar.submit()
		frappe.db.set_value("Journal Entry", jv.name, "linked_auto_repeat", ar.name)

		with self.assertRaisesRegex(frappe.ValidationError, "active Auto Repeat reversal"):
			make_reverse_journal_entry(jv.name)

	def test_auto_repeat_reversal_guard_clears_on_disable(self):
		"""TC-013: After the linked Auto Repeat is disabled, manual reversal succeeds."""
		if not self._auto_repeat_reversal_available():
			self.skipTest("Auto Repeat does not expose repeat_type — Frappe-side WP not deployed")
		from erpnext.accounts.doctype.journal_entry.journal_entry import make_reverse_journal_entry

		jv = self._make_submitted_jv()
		ar = frappe.new_doc("Auto Repeat")
		ar.update(
			{
				"reference_doctype": "Journal Entry",
				"reference_document": jv.name,
				"repeat_type": "Reversal",
				"reverse_on_next_month": 1,
				"start_date": nowdate(),
				"frequency": "",
			}
		)
		ar.flags.ignore_permissions = True
		ar.insert()
		ar.submit()
		frappe.db.set_value("Journal Entry", jv.name, "linked_auto_repeat", ar.name)

		# Disable the AR — guard must release.
		frappe.db.set_value("Auto Repeat", ar.name, "disabled", 1)

		rjv = make_reverse_journal_entry(jv.name)
		self.assertEqual(rjv.reversal_of, jv.name)

	def test_auto_repeat_reversal_default_status(self):
		"""TC-baseline: Fresh JE has empty linked_auto_repeat / auto_reversal_status."""
		jv = self._make_submitted_jv()
		jv.reload()
		self.assertFalse(jv.get("linked_auto_repeat"))
		self.assertFalse(jv.get("auto_reversal_status"))


def make_journal_entry(
	account1,
	account2,
	amount,
	cost_center=None,
	posting_date=None,
	exchange_rate=1,
	save=True,
	submit=False,
	project=None,
	company=None,
):
	if not cost_center:
		cost_center = "_Test Cost Center - _TC"

	jv = frappe.new_doc("Journal Entry")
	jv.posting_date = posting_date or nowdate()
	jv.company = company or "_Test Company"
	jv.remark = "test"
	jv.multi_currency = 1
	jv.set(
		"accounts",
		[
			{
				"account": account1,
				"cost_center": cost_center,
				"project": project,
				"debit_in_account_currency": amount if amount > 0 else 0,
				"credit_in_account_currency": abs(amount) if amount < 0 else 0,
				"exchange_rate": exchange_rate,
			},
			{
				"account": account2,
				"cost_center": cost_center,
				"project": project,
				"credit_in_account_currency": amount if amount > 0 else 0,
				"debit_in_account_currency": abs(amount) if amount < 0 else 0,
				"exchange_rate": exchange_rate,
			},
		],
	)
	if save or submit:
		jv.insert()

		if submit:
			jv.submit()

	return jv
