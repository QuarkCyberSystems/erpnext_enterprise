// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.provide("erpnext.setup");
erpnext.setup.EmployeeController = class EmployeeController extends frappe.ui.form.Controller {
	setup() {
		this.frm.fields_dict.user_id.get_query = function (doc, cdt, cdn) {
			return {
				query: "frappe.core.doctype.user.user.user_query",
				filters: { ignore_user_type: 1 },
			};
		};
		this.frm.fields_dict.reports_to.get_query = function (doc, cdt, cdn) {
			return {
				query: "erpnext.controllers.queries.employee_query",
				filters: [
					["status", "=", "Active"],
					["name", "!=", doc.name],
				],
			};
		};
	}

	refresh() {
		erpnext.toggle_naming_series();
	}
};

frappe.ui.form.on("Employee", {
	setup: function (frm) {
		frm.make_methods = {
			"Bank Account": () => erpnext.utils.make_bank_account(frm.doc.doctype, frm.doc.name),
		};
	},

	onload: function (frm) {
		frm.set_query("department", function () {
			return {
				filters: {
					company: frm.doc.company,
				},
			};
		});
	},

	refresh: function (frm) {
		frm.fields_dict.date_of_birth.datepicker.update({ maxDate: new Date() });

		frm.trigger("add_anniversary_indicator");

		if (!frm.is_new() && !frm.doc.user_id) {
			frm.add_custom_button(__("Create User"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Create User"),
					fields: [
						{
							fieldtype: "Data",
							fieldname: "email",
							label: __("Email"),
							reqd: 1,
							default: frm.doc.company_email || frm.doc.personal_email || frm.doc.user_id,
						},
						{
							fieldtype: "Check",
							fieldname: "create_user_permission",
							label: __("Create User Permission"),
							default: 0,
						},
					],
					primary_action_label: __("Create"),
					primary_action: (values) => {
						if (!values.email) {
							frappe.msgprint(__("Email is required to create a user."));
							return;
						}

						frappe
							.call({
								method: "erpnext.setup.doctype.employee.employee.create_user",
								args: {
									employee: frm.doc.name,
									email: values.email,
									create_user_permission: values.create_user_permission ? 1 : 0,
								},
								freeze: true,
								freeze_message: __("Creating User..."),
							})
							.then(() => {
								dialog.hide();
								frm.reload_doc();
							});
					},
				});

				dialog.show();
			});
		}
	},

	date_of_birth: function (frm) {
		frm.trigger("add_anniversary_indicator");
	},

	date_of_joining: function (frm) {
		frm.trigger("add_anniversary_indicator");
	},

	add_anniversary_indicator: function (frm) {
		if (!frm.sidebar || !frm.sidebar.sidebar) return;

		let $sidebar = frm.sidebar.sidebar;
		let $indicator_section = $sidebar.find(".anniversary-indicator-section");

		if (!$indicator_section.length) {
			$indicator_section = $(`
				<div class="sidebar-section anniversary-indicator-section border-bottom">
					<div class="anniversary-content"></div>
				</div>
			`).insertAfter($sidebar.find(".sidebar-meta-details"));
		}

		let content = "";
		let today = moment().startOf("day");

		if (frm.doc.date_of_birth) {
			let dob = moment(frm.doc.date_of_birth);
			if (dob.date() === today.date() && dob.month() === today.month()) {
				content += `<div class="mb-1"><span class="indicator green"></span> ${__(
					"Today is their Birthday!"
				)}</div>`;
			}
		}

		if (frm.doc.date_of_joining) {
			let doj = moment(frm.doc.date_of_joining);
			if (doj.date() === today.date() && doj.month() === today.month()) {
				let years = today.year() - doj.year();
				if (years > 0) {
					content += `<div class="mb-1"><span class="indicator green"></span> ${__(
						"Today is their {0} Year Work Anniversary!",
						[years]
					)}</div>`;
				}
			}
		}

		if (content) {
			$indicator_section.find(".anniversary-content").html(content);
			$indicator_section.show();
		} else {
			$indicator_section.hide();
		}
	},

	prefered_contact_email: function (frm) {
		frm.events.update_contact(frm);
	},

	personal_email: function (frm) {
		frm.events.update_contact(frm);
	},

	company_email: function (frm) {
		frm.events.update_contact(frm);
	},

	user_id: function (frm) {
		frm.events.update_contact(frm);
	},

	update_contact: function (frm) {
		var prefered_email_fieldname = frappe.model.scrub(frm.doc.prefered_contact_email) || "user_id";
		frm.set_value("prefered_email", frm.fields_dict[prefered_email_fieldname].value);
	},

	status: function (frm) {
		return frm.call({
			method: "deactivate_sales_person",
			args: {
				employee: frm.doc.employee,
				status: frm.doc.status,
			},
		});
	},
});

cur_frm.cscript = new erpnext.setup.EmployeeController({
	frm: cur_frm,
});

frappe.tour["Employee"] = [
	{
		fieldname: "first_name",
		title: "First Name",
		description: __(
			"Enter First and Last name of Employee, based on Which Full Name will be updated. IN transactions, it will be Full Name which will be fetched."
		),
	},
	{
		fieldname: "company",
		title: "Company",
		description: __("Select a Company this Employee belongs to."),
	},
	{
		fieldname: "date_of_birth",
		title: "Date of Birth",
		description: __(
			"Select Date of Birth. This will validate Employees age and prevent hiring of under-age staff."
		),
	},
	{
		fieldname: "date_of_joining",
		title: "Date of Joining",
		description: __(
			"Select Date of joining. It will have impact on the first salary calculation, Leave allocation on pro-rata bases."
		),
	},
	{
		fieldname: "reports_to",
		title: "Reports To",
		description: __(
			"Here, you can select a senior of this Employee. Based on this, Organization Chart will be populated."
		),
	},
];
