frappe.listview_settings["Journal Entry"] = {
	add_fields: [
		"voucher_type",
		"posting_date",
		"total_debit",
		"company",
		"remark",
		"is_reversed",
		"is_reversal",
		"reversed_by",
		"reversal_of",
	],
	get_indicator: function (doc) {
		if (doc.docstatus === 1 && doc.is_reversed) {
			const label = doc.reversed_by
				? __("Reversed by {0}", [doc.reversed_by])
				: __("Reversed");
			return [label, "orange", "is_reversed,=,1"];
		}
		if (doc.docstatus === 1 && doc.is_reversal) {
			const label = doc.reversal_of
				? __("Reversal of {0}", [doc.reversal_of])
				: __("Reversal");
			return [label, "purple", "is_reversal,=,1"];
		}
		if (doc.docstatus === 1) {
			return [__(doc.voucher_type), "blue", `voucher_type,=,${doc.voucher_type}`];
		}
	},
};
