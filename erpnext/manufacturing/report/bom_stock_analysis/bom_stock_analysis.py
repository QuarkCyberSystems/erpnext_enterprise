# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Floor, IfNull, Sum
from frappe.utils.data import comma_and
from pypika.terms import ExistsCriterion


def execute(filters=None):
	qty_to_make = filters.get("qty_to_make")

	if qty_to_make:
		columns = get_columns_with_qty_to_make()
		data = get_data_with_qty_to_make(filters)
		return columns, data
	else:
		data = []
		columns = get_columns_without_qty_to_make()
		bom_data = get_producible_fg_items(filters)
		for row in bom_data:
			data.append(row)

		return columns, data


def get_data_with_qty_to_make(filters):
	data = []
	bom_data = get_bom_data(filters)
	manufacture_details = get_manufacturer_records()

	for row in bom_data:
		required_qty = filters.get("qty_to_make") * row.qty_per_unit
		last_purchase_rate = frappe.db.get_value("Item", row.item_code, "last_purchase_rate")

		data.append(get_report_data(last_purchase_rate, required_qty, row, manufacture_details))

	return data


def get_report_data(last_purchase_rate, required_qty, row, manufacture_details):
	qty_per_unit = row.qty_per_unit if row.qty_per_unit > 0 else 0
	difference_qty = row.actual_qty - required_qty
	return [
		row.item_code,
		row.description,
		row.from_bom_no,
		comma_and(manufacture_details.get(row.item_code, {}).get("manufacturer", []), add_quotes=False),
		comma_and(manufacture_details.get(row.item_code, {}).get("manufacturer_part", []), add_quotes=False),
		qty_per_unit,
		row.actual_qty,
		required_qty,
		difference_qty,
		last_purchase_rate,
		row.actual_qty // qty_per_unit if qty_per_unit else 0,
	]


def get_columns_with_qty_to_make():
	return [
		{
			"fieldname": "item",
			"label": _("Item"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 120,
		},
		{
			"fieldname": "description",
			"label": _("Description"),
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"fieldname": "from_bom_no",
			"label": _("From BOM No"),
			"fieldtype": "Link",
			"options": "BOM",
			"width": 150,
		},
		{
			"fieldname": "manufacturer",
			"label": _("Manufacturer"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "manufacturer_part_number",
			"label": _("Manufacturer Part Number"),
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"fieldname": "qty_per_unit",
			"label": _("Qty Per Unit"),
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"fieldname": "available_qty",
			"label": _("Available Qty"),
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"fieldname": "required_qty",
			"label": _("Required Qty"),
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"fieldname": "difference_qty",
			"label": _("Difference Qty"),
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"fieldname": "last_purchase_rate",
			"label": _("Last Purchase Rate"),
			"fieldtype": "Float",
			"width": 160,
		},
		{
			"fieldname": "producible_fg_item",
			"label": _("Producible FG Item"),
			"fieldtype": "Float",
			"width": 200,
		},
	]


def get_columns_without_qty_to_make():
	return [
		_("Item") + ":Link/Item:150",
		_("Item Name") + "::240",
		_("Description") + "::300",
		_("From BOM No") + "::200",
		_("Required Qty") + ":Float:160",
		_("Producible FG Item") + ":Float:200",
	]


def get_bom_data(filters):
	bom_item_table = "BOM Explosion Item" if filters.get("show_exploded_view") else "BOM Item"

	bom_item = frappe.qb.DocType(bom_item_table)
	bin = frappe.qb.DocType("Bin")

	query = (
		frappe.qb.from_(bom_item)
		.left_join(bin)
		.on(bom_item.item_code == bin.item_code)
		.select(
			bom_item.item_code,
			bom_item.description,
			bom_item.parent.as_("from_bom_no"),
			bom_item.qty_consumed_per_unit.as_("qty_per_unit"),
			IfNull(Sum(bin.actual_qty), 0).as_("actual_qty"),
		)
		.where((bom_item.parent == filters.get("bom")) & (bom_item.parenttype == "BOM"))
		.groupby(bom_item.item_code)
		.orderby(bom_item.idx)
	)

	if filters.get("warehouse"):
		warehouse_details = frappe.db.get_value(
			"Warehouse", filters.get("warehouse"), ["lft", "rgt"], as_dict=1
		)

		if warehouse_details:
			wh = frappe.qb.DocType("Warehouse")
			query = query.where(
				ExistsCriterion(
					frappe.qb.from_(wh)
					.select(wh.name)
					.where(
						(wh.lft >= warehouse_details.lft)
						& (wh.rgt <= warehouse_details.rgt)
						& (bin.warehouse == wh.name)
					)
				)
			)
		else:
			query = query.where(bin.warehouse == filters.get("warehouse"))

	if bom_item_table == "BOM Item":
		query = query.select(bom_item.bom_no, bom_item.is_phantom_item)

	data = query.run(as_dict=True)
	return explode_phantom_boms(data, filters) if bom_item_table == "BOM Item" else data


def explode_phantom_boms(data, filters):
	original_bom = filters.get("bom")
	replacements = []

	for idx, item in enumerate(data):
		if not item.is_phantom_item:
			continue

		filters["bom"] = item.bom_no
		children = get_bom_data(filters)
		filters["bom"] = original_bom

		for child in children:
			child.qty_per_unit = (child.qty_per_unit or 0) * (item.qty_per_unit or 0)

		replacements.append((idx, children))

	for idx, children in reversed(replacements):
		data.pop(idx)
		data[idx:idx] = children

	filters["bom"] = original_bom
	return data


def get_manufacturer_records():
	details = frappe.get_all(
		"Item Manufacturer", fields=["manufacturer", "manufacturer_part_no", "item_code"]
	)

	manufacture_details = frappe._dict()
	for detail in details:
		dic = manufacture_details.setdefault(detail.get("item_code"), {})
		dic.setdefault("manufacturer", []).append(detail.get("manufacturer"))
		dic.setdefault("manufacturer_part", []).append(detail.get("manufacturer_part_no"))

	return manufacture_details


def get_producible_fg_items(filters):
	BOM_ITEM = frappe.qb.DocType("BOM Item")
	BOM = frappe.qb.DocType("BOM")
	BIN = frappe.qb.DocType("Bin")
	WH = frappe.qb.DocType("Warehouse")

	warehouse = filters.get("warehouse")
	warehouse_details = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"], as_dict=1)

	if not warehouse:
		frappe.throw(_("Warehouse is required to get producible FG Items"))

	if warehouse_details:
		bin_subquery = (
			frappe.qb.from_(BIN)
			.join(WH)
			.on(BIN.warehouse == WH.name)
			.select(BIN.item_code, Sum(BIN.actual_qty).as_("actual_qty"))
			.where((WH.lft >= warehouse_details.lft) & (WH.rgt <= warehouse_details.rgt))
			.groupby(BIN.item_code)
		)
	else:
		bin_subquery = (
			frappe.qb.from_(BIN)
			.select(BIN.item_code, Sum(BIN.actual_qty).as_("actual_qty"))
			.where(BIN.warehouse == warehouse)
			.groupby(BIN.item_code)
		)

	query = (
		frappe.qb.from_(BOM_ITEM)
		.join(BOM)
		.on(BOM_ITEM.parent == BOM.name)
		.left_join(bin_subquery)
		.on(BOM_ITEM.item_code == bin_subquery.item_code)
		.select(
			BOM_ITEM.item_code,
			BOM_ITEM.item_name,
			BOM_ITEM.description,
			BOM_ITEM.parent.as_("from_bom_no"),
			(BOM_ITEM.stock_qty / BOM.quantity).as_("qty_per_unit"),
			Floor(bin_subquery.actual_qty / ((Sum(BOM_ITEM.stock_qty)) / BOM.quantity)),
		)
		.where((BOM_ITEM.parent == filters.get("bom")) & (BOM_ITEM.parenttype == "BOM"))
		.groupby(BOM_ITEM.item_code)
		.orderby(BOM_ITEM.idx)
	)

	data = query.run(as_list=True)
	return data
