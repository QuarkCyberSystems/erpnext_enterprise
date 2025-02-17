import frappe
from frappe.utils import flt

from erpnext.stock.doctype.purchase_receipt.purchase_receipt import (
	adjust_incoming_rate_for_pr,
	get_billed_qty_against_purchase_receipt,
)


def execute():
	table = frappe.qb.DocType("Purchase Receipt Item")
	query = (
		frappe.qb.from_(table)
		.select(table.parent)
		.distinct()
		.where((table.amount_difference_with_purchase_invoice > 0) & (table.docstatus == 1))
	)
	pr_names = [item.parent for item in query.run(as_dict=True)]

	for pr_name in pr_names:
		pr_doc = frappe.get_doc("Purchase Receipt", pr_name)
		for item in pr_doc.items:
			adjusted_amt = 0.0
			item_wise_billed_qty = get_billed_qty_against_purchase_receipt(pr_doc)

			if (
				item.billed_amt is not None
				and item.amount is not None
				and item_wise_billed_qty.get(item.name)
			):
				adjusted_amt = (
					flt(item.billed_amt / item_wise_billed_qty.get(item.name)) - flt(item.rate)
				) * item.qty

			adjusted_amt = flt(adjusted_amt * flt(pr_doc.conversion_rate), item.precision("amount"))
			item.db_set("amount_difference_with_purchase_invoice", adjusted_amt, update_modified=False)
		adjust_incoming_rate_for_pr(pr_doc)
