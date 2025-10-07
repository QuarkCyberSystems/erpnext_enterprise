# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.query_builder import DocType

from erpnext.stock.doctype.batch.batch import get_batch_qty


def execute(filters=None):
	if not filters:
		filters = {}

	columns = get_columns()
	data = get_data(filters)

	return columns, data


def get_columns() -> list[dict]:
	columns = [
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 200,
		},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Batch"), "fieldname": "batch", "fieldtype": "Link", "options": "Batch", "width": 200},
		{"label": _("Batch Qty"), "fieldname": "batch_qty", "fieldtype": "Float", "width": 150},
		{"label": _("Stock Qty"), "fieldname": "stock_qty", "fieldtype": "Float", "width": 150},
		{"label": _("Difference"), "fieldname": "difference", "fieldtype": "Float", "width": 150},
	]

	return columns


def get_data(filters):
	item_filter = filters.get("item")
	batch_filter = filters.get("batch")

	Batch = DocType("Batch")

	query = (
		frappe.qb.from_(Batch)
		.select(Batch.item.as_("item_code"), Batch.item_name, Batch.batch_qty, Batch.name.as_("batch_no"))
		.where(Batch.disabled == 0)
	)

	if item_filter:
		query = query.where(Batch.item == item_filter)

	if batch_filter:
		query = query.where(Batch.name == batch_filter)

	batch_list = query.run(as_dict=True)
	data = []
	for batch in batch_list:
		batches = get_batch_qty(batch_no=batch.batch_no)

		if not batches:
			continue

		batch_qty = batch.get("batch_qty", 0)
		actual_qty = sum(b.get("qty", 0) for b in batches)

		difference = batch_qty - actual_qty

		row = {
			"item_code": batch.item_code,
			"item_name": batch.item_name,
			"batch": batch.batch_no,
			"batch_qty": batch_qty,
			"stock_qty": actual_qty,
			"difference": difference,
		}

		data.append(row)

	return data


@frappe.whitelist()
def update_batch_qty(batches=None):
	if not batches:
		return

	batches = json.loads(batches)
	for batch in batches:
		batch_name = batch.get("batch")
		stock_qty = batch.get("stock_qty")

		frappe.db.set_value("Batch", batch_name, "batch_qty", stock_qty)

	frappe.msgprint(_("Batch Qty updated successfully"), alert=True)
