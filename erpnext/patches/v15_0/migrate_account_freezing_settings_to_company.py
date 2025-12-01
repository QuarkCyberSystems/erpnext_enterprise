import frappe


def execute():
	frozen_till = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
	modifier = frappe.db.get_single_value("Accounts Settings", "frozen_accounts_modifier")

	if not frozen_till and not modifier:
		return

	for company in frappe.get_all("Company", pluck="name"):
		frappe.db.set_value(
			"Company",
			company,
			{
				"accounts_frozen_till_date": frozen_till,
				"role_allowed_for_frozen_entries": modifier,
			},
		)
