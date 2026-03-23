// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.query_reports["BOM Stock Analysis"] = {
	filters: [
		{
			fieldname: "bom",
			label: __("BOM"),
			fieldtype: "Link",
			options: "BOM",
			reqd: 1,
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
		},
		{
			fieldname: "qty_to_make",
			label: __("FG Items to Make"),
			fieldtype: "Float",
		},
		{
			fieldname: "show_exploded_view",
			label: __("Show availability of exploded items"),
			fieldtype: "Check",
			default: false,
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.id == "producible_fg_item") {
			if (data["producible_fg_item"] >= data["required_qty"]) {
				value = `<a style='color:green' href="/app/item/${data["producible_fg_item"]}" data-doctype="producible_fg_item">${data["producible_fg_item"]}</a>`;
			} else {
				value = `<a style='color:red' href="/app/item/${data["producible_fg_item"]}" data-doctype="producible_fg_item">${data["producible_fg_item"]}</a>`;
			}
		}
		return value;
	},
};
