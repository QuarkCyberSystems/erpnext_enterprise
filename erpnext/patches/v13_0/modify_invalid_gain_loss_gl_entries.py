import json

import frappe


def execute():
	frappe.reload_doc("accounts", "doctype", "purchase_invoice_advance")
	frappe.reload_doc("accounts", "doctype", "sales_invoice_advance")

	purchase_invoices = frappe.db.sql(
		"""
		select
			PI.company, PI_ADV.parenttype as type, PI_ADV.parent as name
		from
			`tabPurchase Invoice Advance` as PI_ADV join `tabPurchase Invoice` as PI
		on
			PI_ADV.parent = PI.name
		where
			PI_ADV.ref_exchange_rate = 1
			and PI_ADV.docstatus = 1
			and ifnull(PI_ADV.exchange_gain_loss, 0) != 0
		group by
			PI_ADV.parent
	""",
		as_dict=1,
	)

	sales_invoices = frappe.db.sql(
		"""
		select
			SI.company, SI_ADV.parenttype as type, SI_ADV.parent as name
		from
			`tabSales Invoice Advance` as SI_ADV join `tabSales Invoice` as SI
		on
			SI_ADV.parent = SI.name
		where
			SI_ADV.ref_exchange_rate = 1
			and SI_ADV.docstatus = 1
			and ifnull(SI_ADV.exchange_gain_loss, 0) != 0
		group by
			SI_ADV.parent
	""",
		as_dict=1,
	)

	if purchase_invoices + sales_invoices:
		frappe.log_error(
			"Fix invalid gain / loss patch log",
			message=json.dumps(purchase_invoices + sales_invoices, indent=2),
		)

	original_frozen_dates = {}

	for invoice in purchase_invoices + sales_invoices:
		company = invoice.company

		# Unfreeze only once per company
		if company not in original_frozen_dates:
			accounts_frozen_till_date = frappe.get_cached_value(
				"Company", company, "accounts_frozen_till_date"
			)
			original_frozen_dates[company] = accounts_frozen_till_date

			if accounts_frozen_till_date:
				frappe.db.set_value("Company", company, "accounts_frozen_till_date", None)

		try:
			doc = frappe.get_doc(invoice.type, invoice.name)
			doc.docstatus = 2
			doc.make_gl_entries()
			for advance in doc.advances:
				if advance.ref_exchange_rate == 1:
					advance.db_set("exchange_gain_loss", 0, False)
			doc.docstatus = 1
			doc.make_gl_entries()
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			print(f"Failed to correct gl entries of {invoice.name}")

	for company, frozen_date in original_frozen_dates.items():
		if frozen_date:
			frappe.db.set_value("Company", company, "accounts_frozen_till_date", frozen_date)
