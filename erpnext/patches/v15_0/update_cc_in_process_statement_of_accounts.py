import frappe


def execute():
	data = frappe.db.sql(
		"""SELECT name, cc_to FROM `tabProcess Statement Of Accounts` WHERE cc_to IS NOT NULL""", as_dict=True
	)
	for d in data:
		doc = frappe.get_doc("Process Statement Of Accounts", d.name)
		doc.append("cc_to", {"cc": d.cc_to})
		doc.save()
