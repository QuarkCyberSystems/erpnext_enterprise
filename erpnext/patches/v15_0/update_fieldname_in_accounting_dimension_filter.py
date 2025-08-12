import frappe
from frappe.query_builder import DocType


def execute():
	default_accounting_dimension()
	ADF = DocType("Accounting Dimension Filter")
	AD = DocType("Accounting Dimension")

	accounting_dimension_filter = (
		frappe.qb.from_(ADF)
		.join(AD)
		.on(AD.document_type == ADF.accounting_dimension)
		.select(ADF.name, AD.fieldname)
	).run(as_dict=True)

	for doc in accounting_dimension_filter:
		frappe.db.set_value(
			"Accounting Dimension Filter",
			doc.name,
			"fieldname",
			doc.fieldname,
			update_modified=False,
		)


def default_accounting_dimension():
	for accounting_dimension in ["Cost Center", "Project"]:
		frappe.db.set_value(
			"Accounting Dimension Filter",
			{"accounting_dimension": accounting_dimension},
			"fieldname",
			frappe.scrub(accounting_dimension),
			update_modified=False,
		)
