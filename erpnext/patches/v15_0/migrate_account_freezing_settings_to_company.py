import frappe


def execute():
	accounts_settings = frappe.get_doc("Accounts Settings", "Accounts Settings")

	accounts_frozen_till_date = accounts_settings.acc_frozen_upto
	frozen_accounts_modifier = accounts_settings.frozen_accounts_modifier

	for company in frappe.get_all("Company", pluck="name"):
		frappe.db.set_value(
			"Company",
			company,
			{
				"accounts_frozen_till_date": accounts_frozen_till_date,
				"role_allowed_for_frozen_entries": frozen_accounts_modifier,
			},
		)
