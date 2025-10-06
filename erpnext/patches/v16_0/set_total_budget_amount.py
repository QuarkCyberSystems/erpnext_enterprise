import frappe


def execute():
	if frappe.db.has_column("Budget", "total_budget_amount"):
		frappe.db.sql(
			"""
            UPDATE `tabBudget` b
            SET b.total_budget_amount = (
                SELECT SUM(ba.budget_amount)
                FROM `tabBudget Account` ba
                WHERE ba.parent = b.name
            )
            WHERE IFNULL(b.total_budget_amount, 0) = 0
            """
		)
