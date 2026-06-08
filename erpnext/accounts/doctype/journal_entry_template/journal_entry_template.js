// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Journal Entry Template", {
	onload: function (frm) {
		erpnext.accounts.dimensions.setup_dimension_filters(frm, frm.doctype);
		if (frm.is_new()) {
			frappe.call({
				type: "GET",
				method: "erpnext.accounts.doctype.journal_entry_template.journal_entry_template.get_naming_series",
				callback: function (r) {
					if (r.message) {
						frm.set_df_property("naming_series", "options", r.message.split("\n"));
						frm.set_value("naming_series", r.message.split("\n")[0]);
						frm.refresh_field("naming_series");
					}
				},
			});
		}
	},
	refresh: function (frm) {
		frappe.model.set_default_values(frm.doc);

		frm.set_query("account", "accounts", function () {
			var filters = {
				company: frm.doc.company,
				is_group: 0,
			};

			if (!frm.doc.multi_currency) {
				$.extend(filters, {
					account_currency: [
						"in",
						[frappe.get_doc(":Company", frm.doc.company).default_currency, null],
					],
				});
			}

			return { filters: filters };
		});

		frm.set_query("project", "accounts", function (doc, cdt, cdn) {
			let row = frappe.get_doc(cdt, cdn);
			let filters = {
				company: doc.company,
			};
			if (row.party_type == "Customer") {
				filters.customer = row.party;
			}
			return {
				query: "erpnext.controllers.queries.get_project_name",
				filters,
			};
		});

		frm.set_query("party_type", "accounts", function (doc, cdt, cdn) {
			const row = locals[cdt][cdn];

			return {
				query: "erpnext.setup.doctype.party_type.party_type.get_party_type",
				filters: {
					account: row.account,
				},
			};
		});

		apply_template_lock_state(frm);
	},
	voucher_type: function (frm) {
		var add_accounts = function (doc, r) {
			$.each(r, function (i, d) {
				var row = frappe.model.add_child(doc, "Journal Entry Template Account", "accounts");
				row.account = d.account;
			});
			refresh_field("accounts");
		};

		if (!frm.doc.company) return;

		frm.trigger("clear_child");
		switch (frm.doc.voucher_type) {
			case "Bank Entry":
			case "Cash Entry":
				frappe.call({
					type: "GET",
					method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_default_bank_cash_account",
					args: {
						account_type:
							frm.doc.voucher_type == "Bank Entry"
								? "Bank"
								: frm.doc.voucher_type == "Cash Entry"
								? "Cash"
								: null,
						company: frm.doc.company,
					},
					callback: function (r) {
						if (r.message) {
							// If default company bank account not set
							if (!$.isEmptyObject(r.message)) {
								add_accounts(frm.doc, [r.message]);
							}
						}
					},
				});
				break;
			default:
				frm.trigger("clear_child");
		}
	},
	clear_child: function (frm) {
		frappe.model.clear_table(frm.doc, "accounts");
		frm.refresh_field("accounts");
	},
	enable_auto_reversal: function (frm) {
		if (!frm.doc.enable_auto_reversal) {
			frm.set_value({
				auto_reverse_on: "First Day of Next Month",
				auto_reverse_date: null,
				reversal_exchange_rate_type: "Original Rate",
				reversal_tax_mode: "Use Original",
				reversal_cost_center_mode: "Use Original",
				auto_submit_reversal: 0,
			});
		}
	},
	auto_reverse_on: function (frm) {
		if (frm.doc.auto_reverse_on === "First Day of Next Month") {
			frm.set_value("auto_reverse_date", null);
		}
	},
});

// Structural fields frozen once the template is in use (defect WA-0001-04 #1).
// `disabled`, `from_date`, `end_date` are deliberately excluded so the template
// can be retired / date-bounded after lock.
const TEMPLATE_FROZEN_FIELDS = [
	"template_title",
	"voucher_type",
	"naming_series",
	"company",
	"is_opening",
	"multi_currency",
	"lock_on_apply",
	"allow_additional_accounts",
	"enable_auto_reversal",
	"auto_reverse_on",
	"auto_reverse_date",
	"reversal_exchange_rate_type",
	"reversal_tax_mode",
	"reversal_cost_center_mode",
	"auto_submit_reversal",
];

var apply_template_lock_state = function (frm) {
	const onload = frm.doc.__onload || {};

	// Defect WA-0001-04 #4 — global Accounts Settings switch forces Lock Fields
	// on Apply on and prevents users from unchecking it.
	if (onload.enforce_template_field_locking) {
		if (!frm.doc.lock_on_apply) {
			frm.set_value("lock_on_apply", 1);
		}
		frm.set_df_property("lock_on_apply", "read_only", 1);
	}

	if (!onload.in_use) return;

	// Defect WA-0001-04 #1 — template already used by a submitted Journal Entry;
	// freeze its structure. Availability fields stay editable.
	TEMPLATE_FROZEN_FIELDS.forEach((f) => frm.set_df_property(f, "read_only", 1));

	const grid = frm.fields_dict.accounts.grid;
	grid.cannot_add_rows = true;
	grid.cannot_delete_rows = true;
	grid.static_rows = true;
	(frappe.get_meta("Journal Entry Template Account").fields || []).forEach((df) => {
		if (["Section Break", "Column Break", "HTML", "Button"].includes(df.fieldtype)) return;
		grid.update_docfield_property(df.fieldname, "read_only", 1);
	});
	frm.refresh_field("accounts");

	frm.dashboard.add_comment(
		__("This template has been used by a submitted Journal Entry and is locked. You can still disable it or change its From/End dates."),
		"blue",
		true
	);
};
