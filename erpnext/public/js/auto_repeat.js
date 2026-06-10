// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// WP GA-0001-05+06 — an Auto Repeat created by a Journal Entry's auto-reversal
// is fully managed by the JE flow. Grey out every field so the user cannot edit
// its configuration (not even switch it to Copy mode); only disabling it to stop
// the schedule is allowed. The server-side guard in ERPNextAutoRepeat.validate()
// enforces the same rule for bulk edit / API; this is the matching UX.
frappe.ui.form.on("Auto Repeat", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!(frm.doc.__onload && frm.doc.__onload.je_reversal_locked)) return;

		const ALLOWED = ["disabled"];
		const SKIP_TYPES = ["Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"];
		(frm.meta.fields || []).forEach((df) => {
			if (SKIP_TYPES.includes(df.fieldtype)) return;
			if (ALLOWED.includes(df.fieldname)) return;
			frm.set_df_property(df.fieldname, "read_only", 1);
		});

		// also lock the child grids (e.g. auto_repeat_days) fully
		(frm.meta.fields || [])
			.filter((df) => df.fieldtype === "Table")
			.forEach((df) => {
				const grid = frm.fields_dict[df.fieldname] && frm.fields_dict[df.fieldname].grid;
				if (grid) {
					grid.cannot_add_rows = true;
					grid.cannot_delete_rows = true;
					grid.static_rows = true;
				}
			});

		frm.dashboard.add_comment(
			__(
				"This Auto Repeat was created by a Journal Entry auto-reversal and is locked. You can only disable it to stop the schedule."
			),
			"blue",
			true
		);
		frm.refresh_fields();
	},
});
