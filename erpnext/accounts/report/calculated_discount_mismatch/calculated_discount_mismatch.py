# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

DISCOUNT_DOCTYPES = frozenset(
	(
		"POS Invoice",
		"Purchase Invoice",
		"Sales Invoice",
		"Purchase Order",
		"Supplier Quotation",
		"Quotation",
		"Sales Order",
		"Delivery Note",
		"Purchase Receipt",
	)
)
LAST_MODIFIED_DATE_THRESHOLD = "2025-05-30"


def execute(filters: dict | None = None):
	"""Return columns and data for the report.

	This is the main entry point for the report. It accepts the filters as a
	dictionary and should return columns and data. It is called by the framework
	every time the report is refreshed or a filter is updated.
	"""
	columns = get_columns()
	data = get_data()

	return columns, data


def get_columns() -> list[dict]:
	"""Return columns for the report.

	One field definition per column, just like a DocType field definition.
	"""
	return [
		{
			"label": _("Doctype"),
			"fieldname": "doctype",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Document Name"),
			"fieldname": "document_name",
			"fieldtype": "Dynamic Link",
			"options": "doctype",
			"width": 200,
		},
	]


def get_data() -> list[list]:
	"""Return data for the report.

	The report data is a list of rows, with each row being a list of cell values.
	"""
	data = []
	VERSION = frappe.qb.DocType("Version")

	result = (
		frappe.qb.from_(VERSION)
		.select(VERSION.ref_doctype, VERSION.docname, VERSION.data, VERSION.name)
		.where(VERSION.modified > LAST_MODIFIED_DATE_THRESHOLD)
		.where(VERSION.ref_doctype.isin(list(DISCOUNT_DOCTYPES)))
		.run(as_dict=True)
	)

	for row in result:
		changed_data = {entry[0]: entry for entry in frappe.parse_json(row.data).get("changed", [])}

		docstatus = changed_data.get("docstatus")
		if not docstatus or docstatus[2] != 1:
			continue

		if "discount_amount" not in changed_data:
			continue

		data.append({"doctype": row.ref_doctype, "document_name": row.docname})

	return data
