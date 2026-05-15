"""WP GA-0001-05+06: unlock Auto Repeat docs that were submitted in error.

The earlier version of `_maybe_create_template_auto_repeat` called
`ar.submit()` after `ar.insert()`. Auto Repeat is not a submittable
doctype per its JSON, but Frappe still allows .submit() and just sets
docstatus=1 in the DB. The form UI then treats those docs as read-only,
locking the `disabled` checkbox and `status` Select — operators
couldn't cancel a scheduled reversal through the form.

The hook has been fixed (commit 701c61f4629) so newly-created ARs land
at docstatus=0. This patch retroactively unlocks any existing AR docs
that got submitted by the old code.

Idempotent — re-running has no effect (any AR already at docstatus=0
or 2 is left alone). The scheduler gates on status+disabled, not
docstatus, so this is a pure form-UX fix.
"""
import frappe


def execute():
	updated = frappe.db.sql(
		"""
		UPDATE `tabAuto Repeat`
		SET docstatus = 0
		WHERE docstatus = 1
		""",
	)
	# `updated` is None on UPDATE; use the cursor's rowcount via a separate count.
	count = frappe.db.sql(
		"SELECT COUNT(*) FROM `tabAuto Repeat` WHERE docstatus = 0", as_list=True
	)[0][0]
	frappe.db.commit()
	frappe.logger().info(
		f"unlock_auto_repeat_docstatus: total Auto Repeats at docstatus=0 after patch: {count}"
	)
