frappe.provide("erpnext.accounts");

erpnext.accounts.unreconcile_payment = {
	add_unreconcile_btn(frm) {
		if (frm.doc.docstatus == 1) {
			if (
				(frm.doc.doctype == "Journal Entry" &&
					!["Journal Entry", "Bank Entry", "Cash Entry"].includes(frm.doc.voucher_type)) ||
				!["Purchase Invoice", "Sales Invoice", "Journal Entry", "Payment Entry"].includes(
					frm.doc.doctype
				)
			) {
				return;
			}

			frappe.call({
				method: "erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment.doc_has_references",
				args: {
					doctype: frm.doc.doctype,
					docname: frm.doc.name,
				},
				callback: function (r) {
					if (r.message) {
						frm.add_custom_button(
							__("UnReconcile"),
							function () {
								erpnext.accounts.unreconcile_payment.build_unreconcile_dialog(frm);
							},
							__("Actions")
						);
					}
				},
			});
		}
	},

	build_selection_map(frm, selections) {
		// assuming each row is an individual voucher
		// pass this to server side method that creates unreconcile doc for each row
		let selection_map = [];
		// WP GA-0001-03 #6: a Sales/Purchase Invoice with is_return=1 is a
		// credit/debit note that acts as the PAYMENT in its reconciliation (the
		// PRE stores it as payment_name). It must use the payment-side mapping
		// (voucher = the note itself, against = the linked invoice), exactly like
		// a Payment Entry / Journal Entry — NOT the invoice-side mapping. Only a
		// non-return invoice uses the invoice-side mapping.
		let is_invoice_side =
			["Sales Invoice", "Purchase Invoice"].includes(frm.doc.doctype) && !frm.doc.is_return;
		if (is_invoice_side) {
			selection_map = selections.map(function (elem) {
				return {
					company: elem.company,
					voucher_type: elem.reference_doctype,
					voucher_no: elem.reference_name,
					against_voucher_type: frm.doc.doctype,
					against_voucher_no: frm.doc.name,
				};
			});
		} else if (
			["Payment Entry", "Journal Entry", "Sales Invoice", "Purchase Invoice"].includes(
				frm.doc.doctype
			)
		) {
			// Payment Entry, Journal Entry, OR a return-invoice acting as payment
			selection_map = selections.map(function (elem) {
				return {
					company: elem.company,
					voucher_type: frm.doc.doctype,
					voucher_no: frm.doc.name,
					against_voucher_type: elem.reference_doctype,
					against_voucher_no: elem.reference_name,
				};
			});
		}
		return selection_map;
	},

	build_unreconcile_dialog(frm) {
		if (
			["Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry"].includes(frm.doc.doctype)
		) {
			let child_table_fields = [
				{
					label: __("Voucher Type"),
					fieldname: "reference_doctype",
					fieldtype: "Link",
					options: "DocType",
					in_list_view: 1,
					read_only: 1,
				},
				{
					label: __("Voucher No"),
					fieldname: "reference_name",
					fieldtype: "Dynamic Link",
					options: "reference_doctype",
					in_list_view: 1,
					read_only: 1,
				},
				{
					label: __("Allocated Amount"),
					fieldname: "allocated_amount",
					fieldtype: "Currency",
					in_list_view: 1,
					read_only: 1,
					options: "account_currency",
				},
				{
					label: __("Currency"),
					fieldname: "account_currency",
					fieldtype: "Link",
					options: "Currency",
					read_only: 1,
				},
			];
			let unreconcile_dialog_fields = [
				{
					// WP GA-0001-03 #12: user-chosen posting date for the reversal
					label: __("Unreconcile Date"),
					fieldname: "unreconcile_date",
					fieldtype: "Date",
					default: frappe.datetime.get_today(),
					reqd: 1,
				},
				{
					label: __("Allocations"),
					fieldname: "allocations",
					fieldtype: "Table",
					read_only: 1,
					fields: child_table_fields,
					cannot_add_rows: true,
				},
			];

			// get linked payments
			frappe.call({
				method: "erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment.get_linked_payments_for_doc",
				args: {
					company: frm.doc.company,
					doctype: frm.doc.doctype,
					docname: frm.doc.name,
				},
				callback: function (r) {
					if (r.message) {
						// populate child table with allocations
						unreconcile_dialog_fields[0].data = r.message;
						unreconcile_dialog_fields[0].get_data = function () {
							return r.message;
						};

						let d = new frappe.ui.Dialog({
							title: __("UnReconcile Allocations"),
							fields: unreconcile_dialog_fields,
							size: "large",
							primary_action_label: __("UnReconcile"),
							primary_action(values) {
								let selected_allocations = values.allocations.filter((x) => x.__checked);
								if (selected_allocations.length > 0) {
									let selection_map =
										erpnext.accounts.unreconcile_payment.build_selection_map(
											frm,
											selected_allocations
										);
									erpnext.accounts.unreconcile_payment.create_unreconcile_docs(
										selection_map,
										values.unreconcile_date
									);
									d.hide();
								} else {
									frappe.msgprint(__("No Selection"));
								}
							},
						});

						d.show();
					}
				},
			});
		}
	},

	create_unreconcile_docs(selection_map, unreconcile_date) {
		frappe.call({
			method: "erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment.create_unreconcile_doc_for_selection",
			args: {
				selections: selection_map,
				unreconcile_date: unreconcile_date,
			},
		});
	},
};
