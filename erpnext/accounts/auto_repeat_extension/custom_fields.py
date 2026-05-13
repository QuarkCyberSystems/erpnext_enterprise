# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt
"""Custom Fields installer for the ERPNext-side Auto Repeat extension.

These fields are added to frappe's Auto Repeat doctype at install /
migrate time so the ERPNext controller override (ERPNextAutoRepeat) has
the columns it needs. The frappe doctype JSON itself is untouched.

Idempotent — safe to call repeatedly. Wired into erpnext's `after_install`
+ `after_migrate` hooks in erpnext/hooks.py.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def install_auto_repeat_custom_fields():
	"""Install the WP-05+06 Custom Fields on frappe Auto Repeat."""
	create_custom_fields(
		{
			"Auto Repeat": [
				{
					"fieldname": "repeat_type",
					"label": "Repeat Type",
					"fieldtype": "Select",
					"options": "Copy\nReversal",
					"default": "Copy",
					"reqd": 1,
					"insert_after": "reference_document",
					"description": (
						"Copy: deep-copy the source on each schedule. "
						"Reversal: route through erpnext.auto_repeat_handlers "
						"to create a reversal entry instead."
					),
				},
				{
					"fieldname": "erpnext_source_validation_section",
					"label": "Source Validation",
					"fieldtype": "Section Break",
					"insert_after": "repeat_type",
					"collapsible": 1,
				},
				{
					"fieldname": "skip_if_source_cancelled",
					"label": "Skip if Source Cancelled",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "erpnext_source_validation_section",
					"description": "Auto-disable this Auto Repeat when the source is cancelled.",
				},
				{
					"fieldname": "follow_amendment_chain",
					"label": "Follow Amendment Chain",
					"fieldtype": "Check",
					"default": 0,
					"insert_after": "skip_if_source_cancelled",
					"description": "If the source is cancelled, walk amended_from to use the latest live amendment.",
				},
				{
					"fieldname": "current_source_document",
					"label": "Current Source Document",
					"fieldtype": "Dynamic Link",
					"options": "reference_doctype",
					"read_only": 1,
					"no_copy": 1,
					"insert_after": "follow_amendment_chain",
					"description": "Updated at each fire — the doc actually used (post amendment-chain follow).",
				},
			]
		},
		ignore_validate=True,
		update=True,
	)
	frappe.clear_cache(doctype="Auto Repeat")
