from frappe.model.utils.rename_field import rename_field


def execute():
	rename_field("POS Closing Entry", "pos_transactions", "pos_invoices")
	rename_field("POS Closing Entry", "sales_invoice_transactions", "sales_invoices")
