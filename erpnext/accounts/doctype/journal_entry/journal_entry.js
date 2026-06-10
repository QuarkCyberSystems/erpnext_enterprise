// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.accounts");
frappe.provide("erpnext.journal_entry");

frappe.ui.form.on("Journal Entry", {
	setup: function (frm) {
		frm.add_fetch("bank_account", "account", "account");
		frm.ignore_doctypes_on_cancel_all = [
			"Sales Invoice",
			"Purchase Invoice",
			"Journal Entry",
			"Repost Payment Ledger",
			"Asset",
			"Asset Movement",
			"Asset Depreciation Schedule",
			"Repost Accounting Ledger",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
			"Bank Transaction",
			// WP GA-0001-03 / GAP-004: PREs are not cascade-cancellable.
			// The server-side `before_cancel` guard enforces the actual
			// rule (active-PRE-only). See payment_entry.js for the full
			// rationale.
			"Payment Reconciliation Entry",
		];

		frm.trigger("set_queries");
	},

	set_queries(frm) {
		frm.set_query("periodic_entry_difference_account", function () {
			return {
				filters: {
					is_group: 0,
					company: frm.doc.company,
				},
			};
		});

		frm.set_query("stock_asset_account", function () {
			return {
				filters: {
					is_group: 0,
					account_type: "Stock",
					company: frm.doc.company,
				},
			};
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
	},

	get_balance_for_periodic_accounting(frm) {
		frm.call({
			method: "get_balance_for_periodic_accounting",
			doc: frm.doc,
			callback: function (r) {
				refresh_field("accounts");
			},
		});
	},

	refresh: function (frm) {
		erpnext.toggle_naming_series();

		if (frm.doc.docstatus > 0) {
			frm.add_custom_button(
				__("Ledger"),
				function () {
					frappe.route_options = {
						voucher_no: frm.doc.name,
						from_date: frm.doc.posting_date,
						to_date: moment(frm.doc.modified).format("YYYY-MM-DD"),
						company: frm.doc.company,
						finance_book: frm.doc.finance_book,
						categorize_by: "",
						show_cancelled_entries: frm.doc.docstatus === 2,
					};
					frappe.set_route("query-report", "General Ledger");
				},
				__("View")
			);
		}

		if (
			frm.doc.docstatus == 1 &&
			!frm.doc.is_reversal &&
			!frm.doc.is_reversed &&
			!frm.doc.reversal_of
		) {
			frm.add_custom_button(
				__("Reverse Journal Entry"),
				function () {
					return erpnext.journal_entry.reverse_journal_entry(frm);
				},
				__("Actions")
			);
		}

		erpnext.journal_entry.show_reversal_indicators(frm);

		if ((frm.doc.is_reversal || frm.doc.reversal_of) && frm.doc.docstatus === 0) {
			erpnext.journal_entry.lock_reversal_fields(frm);
		}

		if (frm.doc.__islocal) {
			frm.add_custom_button(__("Quick Entry"), function () {
				return erpnext.journal_entry.quick_entry(frm);
			});
		}

		// hide /unhide fields based on currency
		erpnext.journal_entry.toggle_fields_based_on_currency(frm);

		if (
			frm.doc.voucher_type == "Inter Company Journal Entry" &&
			frm.doc.docstatus == 1 &&
			!frm.doc.inter_company_journal_entry_reference
		) {
			frm.add_custom_button(
				__("Create Inter Company Journal Entry"),
				function () {
					frm.trigger("make_inter_company_journal_entry");
				},
				__("Make")
			);
		}

		erpnext.accounts.unreconcile_payment.add_unreconcile_btn(frm);

		if (frm.doc.voucher_type !== "Exchange Gain Or Loss") {
			$.each(frm.doc.accounts || [], function (i, row) {
				erpnext.journal_entry.set_exchange_rate(frm, row.doctype, row.name);
			});
		}

		if (frm.doc.template_applied && frm.doc.from_template && !frm.is_new()) {
			frm._from_template_value = frm.doc.from_template;
			frappe.db.get_doc("Journal Entry Template", frm.doc.from_template).then((tpl) => {
				show_template_indicator(frm);
				frappe.db
					.get_single_value("Accounts Settings", "enforce_template_field_locking")
					.then((enforce) => {
						if (enforce) apply_template_locks(frm, tpl);
					});
			});
		}
	},
	before_save: function (frm) {
		if (frm.doc.docstatus == 0 && !frm.doc.is_system_generated) {
			let payment_entry_references = frm.doc.accounts.filter(
				(elem) => elem.reference_type == "Payment Entry"
			);
			if (payment_entry_references.length > 0) {
				let rows = payment_entry_references.map((x) => "#" + x.idx);
				frappe.throw(
					__("Rows: {0} have 'Payment Entry' as reference_type. This should not be set manually.", [
						frappe.utils.comma_and(rows),
					])
				);
			}
		}
	},
	make_inter_company_journal_entry: function (frm) {
		var d = new frappe.ui.Dialog({
			title: __("Select Company"),
			fields: [
				{
					fieldname: "company",
					fieldtype: "Link",
					label: __("Company"),
					options: "Company",
					get_query: function () {
						return {
							filters: [["Company", "name", "!=", frm.doc.company]],
						};
					},
					reqd: 1,
				},
			],
		});
		d.set_primary_action(__("Create"), function () {
			d.hide();
			var args = d.get_values();
			frappe.call({
				args: {
					name: frm.doc.name,
					voucher_type: frm.doc.voucher_type,
					company: args.company,
				},
				method: "erpnext.accounts.doctype.journal_entry.journal_entry.make_inter_company_journal_entry",
				callback: function (r) {
					if (r.message) {
						var doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					}
				},
			});
		});
		d.show();
	},

	multi_currency: function (frm) {
		erpnext.journal_entry.toggle_fields_based_on_currency(frm);
	},

	respect_cost_center_allocation: function (frm) {
		if ((frm.doc.is_reversal || frm.doc.reversal_of) && frm.doc.docstatus === 0) {
			erpnext.journal_entry.apply_cost_center_lock(frm);
		}
	},

	posting_date: function (frm) {
		if (!frm.doc.multi_currency || !frm.doc.posting_date) return;

		$.each(frm.doc.accounts || [], function (i, row) {
			erpnext.journal_entry.set_exchange_rate(frm, row.doctype, row.name);
		});
	},

	company: function (frm) {
		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Company",
				filters: { name: frm.doc.company },
				fieldname: "cost_center",
			},
			callback: function (r) {
				if (r.message) {
					$.each(frm.doc.accounts || [], function (i, jvd) {
						frappe.model.set_value(jvd.doctype, jvd.name, "cost_center", r.message.cost_center);
					});
				}
			},
		});

		erpnext.accounts.dimensions.update_dimension(frm, frm.doctype);
		erpnext.utils.set_letter_head(frm);
		frm.clear_table("tax_withholding_entries");
	},

	voucher_type: function (frm) {
		if (!frm.doc.company) return null;

		if (
			!(frm.doc.accounts || []).length ||
			((frm.doc.accounts || []).length === 1 && !frm.doc.accounts[0].account)
		) {
			if (["Bank Entry", "Cash Entry"].includes(frm.doc.voucher_type)) {
				return frappe.call({
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
								update_jv_details(frm.doc, [r.message]);
							}
						}
					},
				});
			}
		}
	},

	from_template: function (frm) {
		if (frm.doc.from_template) {
			frappe.db.get_doc("Journal Entry Template", frm.doc.from_template).then((tpl) => {
				apply_template(frm, tpl);
				frm._from_template_value = frm.doc.from_template;
			});
		} else {
			// FR-008 (defect WA-0001-04 #3): warn before clearing if
			// template-derived data exists on the Journal Entry.
			const has_template_data =
				frm.doc.template_applied || (frm.doc.accounts || []).some((r) => r.from_template);
			if (has_template_data) {
				const prev = frm._from_template_value;
				frappe.confirm(
					__(
						"Clearing the template reference will unlock all template-derived fields and account rows on this Journal Entry. Do you want to continue?"
					),
					() => {
						clear_template(frm);
						frm._from_template_value = null;
					},
					() => {
						// Cancelled — restore the link without re-seeding the rows.
						frm.doc.from_template = prev;
						frm.refresh_field("from_template");
					}
				);
			} else {
				clear_template(frm);
				frm._from_template_value = null;
			}
		}
	},

	apply_tds: function (frm) {
		frm.clear_table("tax_withholding_entries");
	},

	enable_auto_reversal: function (frm) {
		// WA-0001-05 #9 — auto-reversal is usable on any JE, not just template-derived.
		// Clearing the switch resets the config so a disabled JE carries no stale
		// settings. Mirrors the Journal Entry Template form.
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

frappe.ui.form.on("Journal Entry Account", {
	before_accounts_remove: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.from_template && frm.doc.template_applied) {
			frappe.throw(
				__(
					"Cannot delete account rows that come from the template. Clear the From Template reference to unlock the rows."
				)
			);
		}
	},
});

// Header fields locked once a template is applied. NOTE: `from_template`
// is intentionally NOT in this list — it's the user's release switch. The
// `before_save` hook on the server detects when `from_template` is blanked
// and tears down `template_applied` + row `from_template` flags, returning
// the JE to a fully editable state. Locking the link field would trap the
// user with no way out (the documented "escape hatch" flow).
const TEMPLATE_HEADER_LOCKS = [
	"voucher_type",
	"company",
	"multi_currency",
	"is_opening",
	"naming_series",
];
const TEMPLATE_AUTO_REVERSAL_LOCKS = [
	"enable_auto_reversal",
	"auto_reverse_on",
	"reversal_exchange_rate_type",
	"reversal_tax_mode",
	"reversal_cost_center_mode",
	"auto_submit_reversal",
];

// Row-level fields locked on template-derived JE rows (defect WA-0001-04 #5).
// Built dynamically so every accounting dimension the template can populate —
// cost_center, project, and any custom Accounting Dimension (Branch,
// Department, ...) — locks too, not just the hard-coded identity fields.
// `erpnext.accounts.dimensions.accounting_dimensions` is loaded in JE onload
// (with_cost_center_and_project=true) and refreshes on every form load.
function template_row_lock_fields() {
	const dims =
		(erpnext.accounts.dimensions && erpnext.accounts.dimensions.accounting_dimensions) || [];
	return Array.from(
		new Set([
			"account",
			"party_type",
			"party",
			"cost_center",
			"project",
			...dims.map((d) => d.fieldname).filter(Boolean),
		])
	);
}

var apply_template = function (frm, tpl) {
	frappe.model.clear_table(frm.doc, "accounts");
	frm.set_value({
		company: tpl.company,
		voucher_type: tpl.voucher_type,
		naming_series: tpl.naming_series,
		is_opening: tpl.is_opening,
		multi_currency: tpl.multi_currency,
		enable_auto_reversal: tpl.enable_auto_reversal || 0,
		auto_reverse_on: tpl.auto_reverse_on || "First Day of Next Month",
		auto_reverse_date: tpl.auto_reverse_date || null,
		reversal_exchange_rate_type: tpl.reversal_exchange_rate_type || "Original Rate",
		reversal_tax_mode: tpl.reversal_tax_mode || "Use Original",
		reversal_cost_center_mode: tpl.reversal_cost_center_mode || "Use Original",
		auto_submit_reversal: tpl.auto_submit_reversal || 0,
	});
	update_jv_details(frm.doc, tpl.accounts, true);
	frm.set_value("template_applied", 1);
	// Field locking is governed solely by the global Accounts Settings switch
	// "Enforce Journal Entry Template Field Locking" (admin-only). The per-template
	// "Lock Fields on Apply" checkbox was removed (WA-0001-04) so users cannot
	// disable locking. The server enforces row/structure locks unconditionally.
	frappe.db
		.get_single_value("Accounts Settings", "enforce_template_field_locking")
		.then((enforce) => {
			if (enforce) apply_template_locks(frm, tpl);
		});
	show_template_indicator(frm);
};

var clear_template = function (frm) {
	frm.set_value({
		template_applied: 0,
		enable_auto_reversal: 0,
		auto_reverse_on: "First Day of Next Month",
		auto_reverse_date: null,
		reversal_exchange_rate_type: "Original Rate",
		reversal_tax_mode: "Use Original",
		reversal_cost_center_mode: "Use Original",
		auto_submit_reversal: 0,
	});
	(frm.doc.accounts || []).forEach((row) => {
		row.from_template = 0;
	});
	remove_template_locks(frm);
	frm.refresh_fields();
};

var apply_template_locks = function (frm, tpl) {
	TEMPLATE_HEADER_LOCKS.forEach((f) => frm.set_df_property(f, "read_only", 1));
	TEMPLATE_AUTO_REVERSAL_LOCKS.forEach((f) => frm.set_df_property(f, "read_only", 1));
	const reverse_date_ro = frm.doc.auto_reverse_on !== "Specific Date";
	frm.set_df_property("auto_reverse_date", "read_only", reverse_date_ro ? 1 : 0);

	// Per-row lock: account / party_type are read-only ONLY on rows where
	// from_template=1. `update_docfield_property` takes a scalar — passing
	// "eval:doc.from_template" makes Frappe store the literal string and
	// `cint()` it to 0 (= editable). Iterate grid rows and mutate each row's
	// docfield individually so user-added rows (when allow_additional_accounts=1)
	// stay fully editable.
	const grid = frm.fields_dict.accounts.grid;
	const lock_fields = template_row_lock_fields();
	// Defect WA-0001-04 #5 — lock a field on a template-derived row ONLY when the
	// source template row actually populated it. This mirrors the server-side
	// validate_template_row_locks, which skips blank template values
	// (`if tpl_val in (None, ""): continue`). Locking unconditionally greyed out
	// fields the template left blank (e.g. party), so the user could not fill
	// them on the JE even though the server would have accepted them.
	// `account` is always populated and is enforced positionally server-side, so
	// it always locks. Template rows map 1:1 in seed order to `tpl.accounts`
	// (update_jv_details appends them in order; static_rows keeps that order).
	const ALWAYS_LOCK = new Set(["account"]);
	const apply_row_locks = () => {
		const tpl_rows = tpl.accounts || [];
		let tpl_idx = 0;
		(grid.grid_rows || []).forEach((row) => {
			if (!row || !row.doc) return;
			// User-added rows (from_template=0) stay fully editable → tpl_row=null.
			const tpl_row = row.doc.from_template ? tpl_rows[tpl_idx++] || {} : null;
			lock_fields.forEach((f) => {
				const df = row.docfields && row.docfields.find((d) => d.fieldname === f);
				if (!df) return;
				df.read_only = tpl_row && (ALWAYS_LOCK.has(f) || tpl_row[f]) ? 1 : 0;
			});
		});
	};
	apply_row_locks();
	grid.cannot_delete_rows = !tpl.allow_additional_accounts;
	grid.cannot_add_rows = !tpl.allow_additional_accounts;
	// NOTE: deliberately NOT setting grid.static_rows here. static_rows=true
	// flips Frappe's grid.is_editable() to false, which disables ALL inline
	// cell editing (debit/credit/user_remark included) and forces row-popup
	// editing — see grid.js is_editable(). Reordering template rows is harmless
	// to data (each row keeps its own locked values) and, if it happens, the
	// server positional account check in validate_template_row_locks rejects it.
	frm.refresh_fields();
};

var remove_template_locks = function (frm) {
	TEMPLATE_HEADER_LOCKS.forEach((f) => frm.set_df_property(f, "read_only", 0));
	TEMPLATE_AUTO_REVERSAL_LOCKS.forEach((f) => frm.set_df_property(f, "read_only", 0));
	frm.set_df_property("auto_reverse_date", "read_only", 0);
	template_row_lock_fields().forEach((f) =>
		frm.fields_dict.accounts.grid.update_docfield_property(f, "read_only", 0)
	);
	frm.fields_dict.accounts.grid.cannot_delete_rows = false;
	frm.fields_dict.accounts.grid.cannot_add_rows = false;
};

var show_template_indicator = function (frm) {
	if (frm.doc.from_template && frm.doc.template_applied && frm.dashboard) {
		frm.dashboard.add_indicator(__("Template: {0}", [frm.doc.from_template]), "blue");
	}
};

var update_jv_details = function (doc, r, mark_from_template) {
	$.each(r, function (i, d) {
		var row = frappe.model.add_child(doc, "Journal Entry Account", "accounts");
		const {
			idx,
			name,
			owner,
			parent,
			parenttype,
			parentfield,
			creation,
			modified,
			modified_by,
			doctype,
			docstatus,
			...fields
		} = d;
		frappe.model.set_value(row.doctype, row.name, fields);
		if (mark_from_template) {
			row.from_template = 1;
		}
	});
	refresh_field("accounts");
};

erpnext.accounts.JournalEntry = class JournalEntry extends frappe.ui.form.Controller {
	onload() {
		this.load_defaults();
		this.setup_queries();
		erpnext.accounts.dimensions.setup_dimension_filters(this.frm, this.frm.doctype);
	}

	load_defaults() {
		//this.frm.show_print_first = true;
		if (this.frm.doc.__islocal && this.frm.doc.company) {
			frappe.model.set_default_values(this.frm.doc);
			$.each(this.frm.doc.accounts || [], function (i, jvd) {
				frappe.model.set_default_values(jvd);
			});
			var posting_date = this.frm.doc.posting_date;
			if (!this.frm.doc.amended_from)
				this.frm.set_value("posting_date", posting_date || frappe.datetime.get_today());
		}
	}

	setup_queries() {
		var me = this;

		// Defect WA-0001-04 #2 — the picker hides disabled templates AND templates
		// whose from_date/end_date window excludes the current posting date. Null
		// bounds are treated as open-ended. The server still re-validates on save.
		me.frm.set_query("from_template", function () {
			return {
				query: "erpnext.accounts.doctype.journal_entry.journal_entry.get_available_templates",
				filters: { posting_date: me.frm.doc.posting_date },
			};
		});

		me.frm.set_query("account", "accounts", function (doc, cdt, cdn) {
			return erpnext.journal_entry.account_query(me.frm);
		});

		me.frm.set_query("party_type", "accounts", function (doc, cdt, cdn) {
			const row = locals[cdt][cdn];

			return {
				query: "erpnext.setup.doctype.party_type.party_type.get_party_type",
				filters: {
					account: row.account,
				},
			};
		});

		me.frm.set_query("reference_name", "accounts", function (doc, cdt, cdn) {
			var jvd = frappe.get_doc(cdt, cdn);

			// journal entry
			if (jvd.reference_type === "Journal Entry") {
				frappe.model.validate_missing(jvd, "account");
				return {
					query: "erpnext.accounts.doctype.journal_entry.journal_entry.get_against_jv",
					filters: {
						account: jvd.account,
						party: jvd.party,
					},
				};
			}

			var out = {
				filters: [[jvd.reference_type, "docstatus", "=", 1]],
			};

			if (["Sales Invoice", "Purchase Invoice"].includes(jvd.reference_type)) {
				out.filters.push([jvd.reference_type, "outstanding_amount", "!=", 0]);
				// Filter by cost center
				if (jvd.cost_center) {
					out.filters.push([jvd.reference_type, "cost_center", "in", ["", jvd.cost_center]]);
				}
				// account filter
				frappe.model.validate_missing(jvd, "account");
				var party_account_field = jvd.reference_type === "Sales Invoice" ? "debit_to" : "credit_to";
				out.filters.push([jvd.reference_type, party_account_field, "=", jvd.account]);
			}

			if (["Sales Order", "Purchase Order"].includes(jvd.reference_type)) {
				// party_type and party mandatory
				frappe.model.validate_missing(jvd, "party_type");
				frappe.model.validate_missing(jvd, "party");

				out.filters.push([jvd.reference_type, "per_billed", "<", 100]);
			}

			if (jvd.party_type && jvd.party) {
				let party_field = "";
				if (jvd.reference_type.indexOf("Sales") === 0) {
					party_field = "customer";
				} else if (jvd.reference_type.indexOf("Purchase") === 0) {
					party_field = "supplier";
				}

				if (party_field) {
					out.filters.push([jvd.reference_type, party_field, "=", jvd.party]);
				}
			}

			return out;
		});
	}

	reference_name(doc, cdt, cdn) {
		var d = frappe.get_doc(cdt, cdn);

		if (d.reference_name) {
			if (d.reference_type === "Purchase Invoice" && !flt(d.debit)) {
				this.get_outstanding("Purchase Invoice", d.reference_name, doc.company, d);
			} else if (d.reference_type === "Sales Invoice" && !flt(d.credit)) {
				this.get_outstanding("Sales Invoice", d.reference_name, doc.company, d);
			} else if (d.reference_type === "Journal Entry" && !flt(d.credit) && !flt(d.debit)) {
				this.get_outstanding("Journal Entry", d.reference_name, doc.company, d);
			}
		}
	}

	get_outstanding(doctype, docname, company, child) {
		var args = {
			doctype: doctype,
			docname: docname,
			party: child.party,
			account: child.account,
			account_currency: child.account_currency,
			company: company,
		};

		return frappe.call({
			method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_outstanding",
			args: { args: args },
			callback: function (r) {
				if (r.message) {
					$.each(r.message, function (field, value) {
						frappe.model.set_value(child.doctype, child.name, field, value);
					});
				}
			},
		});
	}

	accounts_add(doc, cdt, cdn) {
		var row = frappe.get_doc(cdt, cdn);
		row.exchange_rate = 1;
		$.each(doc.accounts, function (i, d) {
			if (d.account && d.party && d.party_type) {
				row.account = d.account;
				row.party = d.party;
				row.party_type = d.party_type;
				row.exchange_rate = d.exchange_rate;
			}
		});

		// set difference
		if (doc.difference) {
			if (doc.difference > 0) {
				row.credit_in_account_currency = doc.difference / row.exchange_rate;
				row.credit = doc.difference;
			} else {
				row.debit_in_account_currency = -doc.difference / row.exchange_rate;
				row.debit = -doc.difference;
			}
		}
		this.frm.cscript.update_totals(doc);

		erpnext.accounts.dimensions.copy_dimension_from_first_row(this.frm, cdt, cdn, "accounts");
	}
};

cur_frm.script_manager.make(erpnext.accounts.JournalEntry);

cur_frm.cscript.update_totals = function (doc) {
	var td = 0.0;
	var tc = 0.0;
	var accounts = doc.accounts || [];
	for (var i in accounts) {
		td += flt(accounts[i].debit, precision("debit", accounts[i]));
		tc += flt(accounts[i].credit, precision("credit", accounts[i]));
	}
	doc = locals[doc.doctype][doc.name];
	doc.total_debit = td;
	doc.total_credit = tc;
	doc.difference = flt(td - tc, precision("difference"));
	refresh_many(["total_debit", "total_credit", "difference"]);
};

cur_frm.cscript.get_balance = function (doc, dt, dn) {
	cur_frm.cscript.update_totals(doc);
	cur_frm.call("get_balance", null, () => {
		cur_frm.refresh();
	});
};

cur_frm.cscript.validate = function (doc, cdt, cdn) {
	cur_frm.cscript.update_totals(doc);
};

frappe.ui.form.on("Journal Entry Account", {
	party: function (frm, cdt, cdn) {
		var d = frappe.get_doc(cdt, cdn);
		if (!d.account && d.party_type && d.party) {
			if (!frm.doc.company) frappe.throw(__("Please select Company"));
			return frm.call({
				method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_party_account_and_currency",
				child: d,
				args: {
					company: frm.doc.company,
					party_type: d.party_type,
					party: d.party,
				},
			});
		}
	},

	account: function (frm, dt, dn) {
		erpnext.journal_entry.set_account_details(frm, dt, dn);
	},

	debit_in_account_currency: function (frm, cdt, cdn) {
		erpnext.journal_entry.set_exchange_rate(frm, cdt, cdn);
	},

	credit_in_account_currency: function (frm, cdt, cdn) {
		erpnext.journal_entry.set_exchange_rate(frm, cdt, cdn);
	},

	debit: function (frm, dt, dn) {
		frm.cscript.update_totals(frm.doc);
	},

	credit: function (frm, dt, dn) {
		frm.cscript.update_totals(frm.doc);
	},

	exchange_rate: function (frm, cdt, cdn) {
		var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
		var row = locals[cdt][cdn];

		if (row.account_currency == company_currency || !frm.doc.multi_currency) {
			frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
		}

		erpnext.journal_entry.set_debit_credit_in_company_currency(frm, cdt, cdn);
	},
});

frappe.ui.form.on("Journal Entry Account", "accounts_remove", function (frm) {
	frm.cscript.update_totals(frm.doc);
});

$.extend(erpnext.journal_entry, {
	toggle_fields_based_on_currency: function (frm) {
		var fields = ["currency_section", "account_currency", "exchange_rate", "debit", "credit"];

		var grid = frm.get_field("accounts").grid;
		if (grid) grid.set_column_disp(fields, frm.doc.multi_currency);

		// dynamic label
		var field_label_map = {
			debit_in_account_currency: "Debit",
			credit_in_account_currency: "Credit",
		};

		$.each(field_label_map, function (fieldname, label) {
			frm.fields_dict.accounts.grid.update_docfield_property(
				fieldname,
				"label",
				frm.doc.multi_currency ? label + " in Account Currency" : label
			);
		});
	},

	set_debit_credit_in_company_currency: function (frm, cdt, cdn) {
		var row = locals[cdt][cdn];

		frappe.model.set_value(
			cdt,
			cdn,
			"debit",
			flt(flt(row.debit_in_account_currency) * row.exchange_rate, precision("debit", row))
		);

		frappe.model.set_value(
			cdt,
			cdn,
			"credit",
			flt(flt(row.credit_in_account_currency) * row.exchange_rate, precision("credit", row))
		);

		frm.cscript.update_totals(frm.doc);
	},

	set_exchange_rate: function (frm, cdt, cdn) {
		var company_currency = frappe.get_doc(":Company", frm.doc.company).default_currency;
		var row = locals[cdt][cdn];

		if (row.account_currency == company_currency || !frm.doc.multi_currency) {
			row.exchange_rate = 1;
			erpnext.journal_entry.set_debit_credit_in_company_currency(frm, cdt, cdn);
		} else if (!row.exchange_rate || row.exchange_rate == 1 || row.account_type == "Bank") {
			frappe.call({
				method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_exchange_rate",
				args: {
					posting_date: frm.doc.posting_date,
					account: row.account,
					account_currency: row.account_currency,
					company: frm.doc.company,
					reference_type: cstr(row.reference_type),
					reference_name: cstr(row.reference_name),
					debit: flt(row.debit_in_account_currency),
					credit: flt(row.credit_in_account_currency),
					exchange_rate: row.exchange_rate,
				},
				callback: function (r) {
					if (r.message) {
						row.exchange_rate = r.message;
						erpnext.journal_entry.set_debit_credit_in_company_currency(frm, cdt, cdn);
					}
				},
			});
		} else {
			erpnext.journal_entry.set_debit_credit_in_company_currency(frm, cdt, cdn);
		}
		refresh_field("exchange_rate", cdn, "accounts");
	},

	quick_entry: function (frm) {
		var naming_series_options = frm.fields_dict.naming_series.df.options;
		var naming_series_default =
			frm.fields_dict.naming_series.df.default || naming_series_options.split("\n")[0];

		var dialog = new frappe.ui.Dialog({
			title: __("Quick Journal Entry"),
			fields: [
				{ fieldtype: "Currency", fieldname: "debit", label: __("Amount"), reqd: 1 },
				{
					fieldtype: "Link",
					fieldname: "debit_account",
					label: __("Debit Account"),
					reqd: 1,
					options: "Account",
					get_query: function () {
						return erpnext.journal_entry.account_query(frm);
					},
				},
				{
					fieldtype: "Link",
					fieldname: "credit_account",
					label: __("Credit Account"),
					reqd: 1,
					options: "Account",
					get_query: function () {
						return erpnext.journal_entry.account_query(frm);
					},
				},
				{
					fieldtype: "Date",
					fieldname: "posting_date",
					label: __("Date"),
					reqd: 1,
					default: frm.doc.posting_date,
				},
				{ fieldtype: "Small Text", fieldname: "remark", label: __("Remark") },
				{
					fieldtype: "Select",
					fieldname: "naming_series",
					label: __("Series"),
					reqd: 1,
					options: naming_series_options,
					default: naming_series_default,
				},
			],
		});

		dialog.set_primary_action(__("Save"), function () {
			var btn = this;
			var values = dialog.get_values();

			frm.set_value("posting_date", values.posting_date);
			frm.set_value("naming_series", values.naming_series);
			if (values.remark) {
				frm.set_value("custom_remark", 1);
				frm.set_value("remark", values.remark);
			} else {
				frm.set_value("custom_remark", 0);
				frm.set_value("remark", "");
			}

			// clear table is used because there might've been an error while adding child
			// and cleanup didn't happen
			frm.clear_table("accounts");

			// using grid.add_new_row() to add a row in UI as well as locals
			// this is required because triggers try to refresh the grid

			var debit_row = frm.fields_dict.accounts.grid.add_new_row();
			frappe.model.set_value(debit_row.doctype, debit_row.name, "account", values.debit_account);
			frappe.model.set_value(
				debit_row.doctype,
				debit_row.name,
				"debit_in_account_currency",
				values.debit
			);

			var credit_row = frm.fields_dict.accounts.grid.add_new_row();
			frappe.model.set_value(credit_row.doctype, credit_row.name, "account", values.credit_account);
			frappe.model.set_value(
				credit_row.doctype,
				credit_row.name,
				"credit_in_account_currency",
				values.debit
			);

			frm.save();

			dialog.hide();
		});

		dialog.show();
	},

	account_query: function (frm) {
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
	},

	reverse_journal_entry: function (frm) {
		frappe.model.open_mapped_doc({
			method: "erpnext.accounts.doctype.journal_entry.journal_entry.make_reverse_journal_entry",
			frm: frm,
		});
	},
});

$.extend(erpnext.journal_entry, {
	set_account_details: function (frm, dt, dn) {
		var d = locals[dt][dn];
		if (d.account) {
			if (!frm.doc.company) frappe.throw(__("Please select Company first"));
			if (!frm.doc.posting_date) frappe.throw(__("Please select Posting Date first"));

			return frappe.call({
				method: "erpnext.accounts.doctype.journal_entry.journal_entry.get_account_details_and_party_type",
				args: {
					account: d.account,
					date: frm.doc.posting_date,
					company: frm.doc.company,
					debit: flt(d.debit_in_account_currency),
					credit: flt(d.credit_in_account_currency),
					exchange_rate: d.exchange_rate,
				},
				callback: function (r) {
					if (r.message) {
						$.extend(d, r.message);
						erpnext.journal_entry.set_amount_on_last_row(frm, dt, dn);
						erpnext.journal_entry.set_debit_credit_in_company_currency(frm, dt, dn);
						refresh_field("accounts");
					}
				},
			});
		} else {
			erpnext.journal_entry.clear_fields(frm, dt, dn);
		}
	},
	set_amount_on_last_row: function (frm, dt, dn) {
		let row = locals[dt][dn];
		let length = frm.doc.accounts.length;
		if (row.idx != length) return;

		let difference = frm.doc.accounts.reduce((total, row) => {
			if (row.idx == length) return total;

			return total + row.debit - row.credit;
		}, 0);

		if (difference) {
			if (difference > 0) {
				row.credit_in_account_currency = difference / row.exchange_rate;
				row.credit = difference;
			} else {
				row.debit_in_account_currency = -difference / row.exchange_rate;
				row.debit = -difference;
			}
		}
		refresh_field("accounts");
	},
	clear_fields: function (frm, dt, dn) {
		let row = locals[dt][dn];

		row.party_type = null;
		row.party = null;
		row.bank_account = null;

		frm.refresh_field("accounts");
	},
	show_reversal_indicators: function (frm) {
		if (frm.doc.is_reversed && frm.doc.reversed_by) {
			frm.dashboard.add_indicator(
				__("Reversed by {0}", [
					`<a href="/app/journal-entry/${frm.doc.reversed_by}">${frm.doc.reversed_by}</a>`,
				]),
				"orange"
			);
		}
		if (frm.doc.reversal_of) {
			frm.dashboard.add_indicator(
				__("Reversal of {0}", [
					`<a href="/app/journal-entry/${frm.doc.reversal_of}">${frm.doc.reversal_of}</a>`,
				]),
				"blue"
			);
		}
	},
	lock_reversal_fields: function (frm) {
		// On a reversal draft, everything must be structurally identical to
		// the original — the user cannot edit any field, add/delete rows, or
		// change row values. Only docstatus transitions (save → submit) and
		// the cost-center override switch are user-driven.
		const ALWAYS_EDITABLE = new Set([
			// The override flag itself must remain editable — that's how the
			// user opts into re-resolving cost centers. The server-side
			// validator (validate_reversal_locked_fields) skips cost_center
			// diff when this flag is unchecked, so client + server agree.
			"respect_cost_center_allocation",
			// WA-0001-01 #6 — the reversal's own posting date and remark are the
			// operator's to set (e.g. post the reversal in a later period / explain
			// it). The server validator does not lock these.
			"posting_date",
			"remark",
		]);
		// WA-0001-01 #6 — per-line remark stays editable on the reversal too.
		const CHILD_ALWAYS_EDITABLE = new Set(["user_remark"]);
		const SKIP_TYPES = new Set([
			"Section Break", "Column Break", "Tab Break", "HTML", "Button",
			"Heading",
			// Table fields are locked at the grid level (cannot_add_rows,
			// cannot_delete_rows, static_rows, plus per-column docfield
			// read_only). Setting read_only on the parent Table field flips
			// `grid.display_status` to "Read", which in base_control.js
			// FORCES every child field to Read regardless of its own
			// `df.read_only` — overriding apply_cost_center_lock and any
			// other per-field unlock we do later.
			"Table", "Table MultiSelect",
		]);

		// Lock all parent doctype fields
		(frm.meta.fields || []).forEach((df) => {
			if (SKIP_TYPES.has(df.fieldtype)) return;
			if (ALWAYS_EDITABLE.has(df.fieldname)) return;
			frm.set_df_property(df.fieldname, "read_only", 1);
		});

		// Lock the accounts grid: no add, no delete, no inline-row editing
		const accounts_grid = frm.fields_dict.accounts && frm.fields_dict.accounts.grid;
		if (accounts_grid) {
			accounts_grid.cannot_add_rows = true;
			accounts_grid.cannot_delete_rows = true;
			accounts_grid.static_rows = true;
			// Lock every column on each row (Journal Entry Account child
			// doctype). We bypass `accounts_grid.update_docfield_property`
			// because that helper throws when any single row's `docfields`
			// list doesn't include the named field (it can lag the child
			// meta — perm-filtered fields, custom fields added after the row
			// rendered, etc.), and one throw aborts the rest of the loop,
			// leaving most child fields unlocked. Mutating the docfield
			// objects directly is silent on misses and gives identical
			// runtime behaviour for the fields that do exist.
			const child_meta = frappe.get_meta("Journal Entry Account");
			(child_meta.fields || []).forEach((df) => {
				if (SKIP_TYPES.has(df.fieldtype)) return;
				if (CHILD_ALWAYS_EDITABLE.has(df.fieldname)) return;
				erpnext.journal_entry.set_grid_field_property(
					accounts_grid, df.fieldname, "read_only", 1
				);
				erpnext.journal_entry.set_grid_field_property(
					accounts_grid, df.fieldname, "allow_on_submit", 0
				);
			});
		}
		erpnext.journal_entry.apply_cost_center_lock(frm);
		frm.refresh_field("accounts");
	},
	set_grid_field_property: function (grid, fieldname, property, value) {
		// Safe replacement for grid.update_docfield_property — never throws
		// if a row is missing the field, and also patches the grid-level
		// docfields list so newly added rows pick up the change.
		(grid.grid_rows || []).forEach((row) => {
			const df = row?.docfields?.find((d) => d.fieldname === fieldname);
			if (df) df[property] = value;
		});
		const parent_df = (grid.docfields || []).find((d) => d.fieldname === fieldname);
		if (parent_df) parent_df[property] = value;
	},
	apply_cost_center_lock: function (frm) {
		// WP GA-0001-01: cost_center on a reversal is ALWAYS read-only — the user
		// must never set it by hand.
		//   flag ON  → row cost_center mirrors the original (unchanged)
		//   flag OFF → the server re-resolves it from the cost-center allocation
		//              active at the reversal posting date (maybe_reresolve_cost_center)
		// Either way the value is system-controlled, not user-entered, so the
		// column stays locked in both modes.
		const accounts_grid = frm.fields_dict.accounts && frm.fields_dict.accounts.grid;
		if (!accounts_grid) return;
		const read_only = 1;

		// Update the grid-level docfield (affects future row-dialog renders
		// and inline grid columns).
		erpnext.journal_entry.set_grid_field_property(
			accounts_grid, "cost_center", "read_only", read_only
		);

		// If a row dialog is already open, the Field control cached
		// `read_only` at render time — patch the live control too so the
		// toggle is immediate, no close-reopen required.
		const open = accounts_grid.open_grid_row;
		if (open && open.grid_form) {
			const live = open.grid_form.fields_dict && open.grid_form.fields_dict.cost_center;
			if (live) {
				live.df.read_only = read_only;
				live.refresh();
			}
		}

		frm.refresh_field("accounts");
	},
});
