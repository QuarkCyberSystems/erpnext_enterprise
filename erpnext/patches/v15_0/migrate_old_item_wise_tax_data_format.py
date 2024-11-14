import json

import frappe
from frappe.utils import flt

from erpnext.controllers.taxes_and_totals import ItemWiseTaxDetail


def execute():
	# Get all DocTypes that have the 'item_wise_tax_details' field
	doctypes_with_tax_details = frappe.get_all(
		"DocField", filters={"fieldname": "item_wise_tax_details"}, fields=["parent"], pluck="parent"
	)
	for doctype in doctypes_with_tax_details:
		# Get all documents of this DocType that have data in 'item_wise_tax_details'
		docs = frappe.get_all(
			doctype,
			filters={"item_wise_tax_details": ["is", "set"]},
			fields=["name", "item_wise_tax_details"],
		)
		for doc in docs:
			if not doc.item_wise_tax_details:
				continue

			updated_tax_details = {}
			needs_update = False

			for item, tax_data in json.loads(doc.item_wise_tax_details).items():
				if isinstance(tax_data, list) and len(tax_data) == 2:
					updated_tax_details[item] = ItemWiseTaxDetail(
						tax_rate=tax_data[0],
						tax_amount=tax_data[1],
						# can't be reliably reconstructed since it depends on the tax type
						# (actual, net, previous line total, previous line net, etc)
						net_amount=0.0,
					)
					needs_update = True
				elif isinstance(tax_data, str):
					updated_tax_details[item] = ItemWiseTaxDetail(
						tax_rate=flt(tax_data),
						tax_amount=0.0,
						net_amount=0.0,
					)
					needs_update = True
				else:
					updated_tax_details[item] = tax_data

			if needs_update:
				frappe.db.set_value(
					doctype,
					doc.name,
					"item_wise_tax_details",
					json.dumps(updated_tax_details),
					update_modified=False,
				)

		frappe.db.commit()

	print("Migration of old item-wise tax data format completed for all relevant DocTypes.")
