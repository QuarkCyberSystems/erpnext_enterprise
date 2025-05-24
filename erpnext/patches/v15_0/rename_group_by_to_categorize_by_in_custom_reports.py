import frappe


def execute():
	frappe.db.sql(
		"""
		UPDATE `tabReport`
		SET `json` = JSON_SET(
			JSON_REMOVE(json, '$.filters.group_by'),
			'$.filters.categorize_by',
			REPLACE(JSON_UNQUOTE(JSON_EXTRACT(json, '$.filters.group_by')), 'Group', 'Categorize')
		)
		WHERE
			JSON_CONTAINS_PATH(json, 'one', '$.filters.group_by')
			AND `reference_report` = CASE
				WHEN `reference_report` = 'Supplier Quotation Comparison' THEN 'Supplier Quotation Comparison'
				ELSE 'General Ledger'
			END
			AND `report_type` = 'Custom Report'
		"""
	)
