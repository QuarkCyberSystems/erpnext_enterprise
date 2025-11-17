import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day


def execute():
	budgets = frappe.get_all("Budget", filters={"docstatus": ["in", [0, 1]]}, pluck="name")

	for budget in budgets:
		old_budget = frappe.get_doc("Budget", budget)

		old_accounts = frappe.get_all(
			"Budget Account",
			filters={"parent": old_budget.name},
			fields=["account", "budget_amount"],
			order_by="idx asc",
		)

		if not old_accounts:
			continue

		old_distribution = []
		if old_budget.monthly_distribution:
			old_distribution = frappe.get_all(
				"Monthly Distribution Percentage",
				filters={"parent": old_budget.monthly_distribution},
				fields=["percentage_allocation"],
				order_by="idx asc",
			)

		if old_distribution:
			percentage_list = [flt(d.percentage) for d in old_distribution]
		else:
			percentage_list = [100 / 12] * 12

		fy = frappe.get_doc("Fiscal Year", old_budget.fiscal_year)
		fy_start = fy.year_start_date
		fy_end = fy.year_end_date

		for acc in old_accounts:
			new = frappe.new_doc("Budget")

			new.company = old_budget.company
			new.cost_center = old_budget.cost_center
			new.project = old_budget.project
			new.fiscal_year = fy.name

			new.from_fiscal_year = fy.name
			new.to_fiscal_year = fy.name
			new.budget_start_date = fy_start
			new.budget_end_date = fy_end

			new.account = acc.account
			new.budget_amount = flt(acc.budget_amount)
			new.distribution_frequency = "Monthly"

			new.distribute_equally = 1 if len(set(percentage_list)) == 1 else 0

			fields_to_copy = [
				"applicable_on_material_request",
				"action_if_annual_budget_exceeded_on_mr",
				"action_if_accumulated_monthly_budget_exceeded_on_mr",
				"applicable_on_purchase_order",
				"action_if_annual_budget_exceeded_on_po",
				"action_if_accumulated_monthly_budget_exceeded_on_po",
				"applicable_on_booking_actual_expenses",
				"action_if_annual_budget_exceeded",
				"action_if_accumulated_monthly_budget_exceeded",
				"applicable_on_cumulative_expense",
				"action_if_annual_exceeded_on_cumulative_expense",
				"action_if_accumulated_monthly_exceeded_on_cumulative_expense",
			]

			for field in fields_to_copy:
				if hasattr(old_budget, field):
					new.set(field, old_budget.get(field))

			start = fy_start
			for percentage in percentage_list:
				row_start = get_first_day(start)
				row_end = get_last_day(start)

				new.append(
					"budget_distribution",
					{
						"start_date": row_start,
						"end_date": row_end,
						"percent": percentage,
						"amount": new.budget_amount * percentage / 100,
					},
				)

				start = add_months(start, 1)

			new.flags.ignore_validate = True
			new.flags.ignore_links = True

			new.insert(ignore_permissions=True, ignore_mandatory=True)

			if old_budget.docstatus == 1:
				new.submit()

		if old_budget.docstatus == 1:
			old_budget.cancel()
		else:
			old_budget.delete()
