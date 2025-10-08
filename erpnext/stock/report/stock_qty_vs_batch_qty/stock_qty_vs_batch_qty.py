# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.query_builder.functions import Sum


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

	stock_ledger_entry = frappe.qb.DocType("Stock Ledger Entry")
	batch_ledger = frappe.qb.DocType("Serial and Batch Entry")
	batch_table = frappe.qb.DocType("Batch")

	query = (
		frappe.qb.from_(stock_ledger_entry)
		.inner_join(batch_ledger)
		.on(stock_ledger_entry.serial_and_batch_bundle == batch_ledger.parent)
		.inner_join(batch_table)
		.on(batch_ledger.batch_no == batch_table.name)
		.select(
			batch_table.item.as_("item_code"),
			batch_table.item_name.as_("item_name"),
			batch_table.name.as_("batch"),
			batch_table.batch_qty.as_("batch_qty"),
			Sum(batch_ledger.qty).as_("stock_qty"),
			(Sum(batch_ledger.qty) - batch_table.batch_qty).as_("difference"),
		)
		.where(batch_table.disabled == 0)
		.where(stock_ledger_entry.is_cancelled == 0)
		.groupby(batch_table.name)
		.having((Sum(batch_ledger.qty) - batch_table.batch_qty) != 0)
	)

	if item_filter:
		query = query.where(batch_table.item == item_filter)

	if batch_filter:
		query = query.where(batch_table.name == batch_filter)

	data = query.run(as_dict=True)

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
