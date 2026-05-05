frappe.listview_settings["Journal Entry"] = {
	add_fields: [
		"voucher_type",
		"posting_date",
		"total_debit",
		"company",
		"remark",
		"is_reversed",
		"is_reversal",
	],
	get_indicator: function (doc) {
		if (doc.docstatus === 1 && doc.is_reversed) {
			return [__("Reversed"), "orange", "is_reversed,=,1"];
		}
		if (doc.docstatus === 1 && doc.is_reversal) {
			return [__("Reversal"), "purple", "is_reversal,=,1"];
		}
		if (doc.docstatus === 1) {
			return [__(doc.voucher_type), "blue", `voucher_type,=,${doc.voucher_type}`];
		}
	},
};
