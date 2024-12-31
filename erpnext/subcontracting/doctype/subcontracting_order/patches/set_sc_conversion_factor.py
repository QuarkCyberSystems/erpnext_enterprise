import frappe


def execute():
	# Calculate and set sc_conversion_factor for draft Subcontracting Orders if value is 0

	subcontracting_order_items = frappe.get_all(
		"Subcontracting Order Item",
		filters={"docstatus": 0, "sc_conversion_factor": 0},
		fields=["name", "parent", "purchase_order_item", "qty"],
	)
	for subcontracting_order_item in subcontracting_order_items:
		service_item_qty = frappe.get_value(
			"Subcontracting Order Service Item",
			filters={
				"purchase_order_item": subcontracting_order_item.purchase_order_item,
				"parent": subcontracting_order_item.parent,
			},
			fieldname=["qty"],
		)
		frappe.set_value(
			"Subcontracting Order Item",
			subcontracting_order_item.name,
			"sc_conversion_factor",
			service_item_qty / subcontracting_order_item.qty,
		)
