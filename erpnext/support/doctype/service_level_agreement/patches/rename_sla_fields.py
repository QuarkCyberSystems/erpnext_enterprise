import frappe
from frappe.custom.doctype.custom_field.custom_field import rename_fieldname


def execute():
	doctypes = frappe.get_all("Service Level Agreement", pluck="document_type")
	for doctype in doctypes:
		rename_fieldname(doctype + "-resolution_by", "sla_resolution_by")
		rename_fieldname(doctype + "-resolution_date", "sla_resolution_date")
