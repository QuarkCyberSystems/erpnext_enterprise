import frappe
from frappe import scrub
from frappe.model.meta import get_field_precision
from frappe.utils import flt

from erpnext.accounts.report.calculated_discount_mismatch.calculated_discount_mismatch import (
	DISCOUNT_DOCTYPES,
	LAST_MODIFIED_DATE_THRESHOLD,
)


def execute():
	for doctype in DISCOUNT_DOCTYPES:
		documents = frappe.get_all(
			doctype,
			{
				"docstatus": 0,
				"modified": [">", LAST_MODIFIED_DATE_THRESHOLD],
				"discount_amount": ["is", "set"],
			},
			[
				"name",
				"additional_discount_percentage",
				"discount_amount",
				"apply_discount_on",
				"grand_total",
				"net_total",
			],
		)

		if not documents:
			continue

		precision = get_field_precision(frappe.get_meta(doctype).get_field("additional_discount_percentage"))
		mismatched_documents = []

		for doc in documents:
			discount_applied_on = scrub(doc.apply_discount_on)

			calculated_discount_amount = flt(
				doc.additional_discount_percentage * doc.get(discount_applied_on) / 100,
				precision,
			)

			if calculated_discount_amount != doc.discount_amount:
				mismatched_documents.append(doc.name)

		if mismatched_documents:
			frappe.db.set_value(
				doctype,
				{
					"name": ["in", mismatched_documents],
				},
				"additional_discount_percentage",
				0,
			)
