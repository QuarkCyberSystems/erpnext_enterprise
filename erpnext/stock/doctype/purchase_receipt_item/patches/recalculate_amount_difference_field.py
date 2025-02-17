import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from erpnext.accounts.utils import get_fiscal_year
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import adjust_incoming_rate_for_pr


def execute():
	fiscal_year_dates = get_fiscal_year(frappe.utils.datetime.date.today())
	table = frappe.qb.DocType("Purchase Receipt Item")
	parent = frappe.qb.DocType("Purchase Receipt")
	query = (
		frappe.qb.from_(table)
		.join(parent)
		.on(table.parent == parent.name)
		.select(
			table.parent,
			table.name,
			table.amount,
			table.billed_amt,
			table.amount_difference_with_purchase_invoice,
			table.rate,
			table.qty,
			parent.conversion_rate,
		)
		.where(
			(table.amount_difference_with_purchase_invoice != 0)
			& (table.docstatus == 1)
			& (parent.posting_date.between(fiscal_year_dates[1], fiscal_year_dates[2]))
		)
	)
	result = query.run(as_dict=True)

	item_wise_billed_qty = get_billed_qty_against_purchase_receipt([item.name for item in result])

	for item in result:
		adjusted_amt = 0.0

		if item.billed_amt is not None and item.amount is not None and item_wise_billed_qty.get(item.name):
			adjusted_amt = (
				flt(item.billed_amt / item_wise_billed_qty.get(item.name)) - flt(item.rate)
			) * item.qty
		adjusted_amt = flt(
			adjusted_amt * flt(item.conversion_rate), frappe.get_precision("Purchase Receipt Item", "amount")
		)

		if adjusted_amt != item.amount_difference_with_purchase_invoice:
			frappe.db.set_value(
				"Purchase Receipt Item",
				item.name,
				"amount_difference_with_purchase_invoice",
				adjusted_amt,
				update_modified=False,
			)
			adjust_incoming_rate_for_pr(frappe.get_doc("Purchase Receipt", item.parent))


def get_billed_qty_against_purchase_receipt(pr_names):
	table = frappe.qb.DocType("Purchase Invoice Item")
	query = (
		frappe.qb.from_(table)
		.select(table.pr_detail, Sum(table.qty).as_("qty"))
		.where((table.pr_detail.isin(pr_names)) & (table.docstatus == 1))
	)
	invoice_data = query.run(as_list=1)

	if not invoice_data:
		return frappe._dict()
	return frappe._dict(invoice_data)
