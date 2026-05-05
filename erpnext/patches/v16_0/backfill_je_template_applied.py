import frappe


def execute():
	"""
	Backfill template_applied on JE and from_template on JE Account child rows
	for Journal Entries that were created from a template before GA-0001-04
	introduced these flags. Idempotent.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry`
		SET template_applied = 1
		WHERE
			IFNULL(from_template, '') != ''
			AND IFNULL(template_applied, 0) = 0
		"""
	)

	je_rows = frappe.db.sql(
		"""
		SELECT name, from_template
		FROM `tabJournal Entry`
		WHERE template_applied = 1
		""",
		as_dict=True,
	)

	skipped_missing_template = 0
	matched_rows_total = 0

	for je in je_rows:
		if not frappe.db.exists("Journal Entry Template", je.from_template):
			skipped_missing_template += 1
			continue

		template_rows = frappe.get_all(
			"Journal Entry Template Account",
			filters={"parent": je.from_template, "parenttype": "Journal Entry Template"},
			fields=["account", "party_type"],
		)
		template_keys = [(r.account, r.party_type or "") for r in template_rows]

		je_account_rows = frappe.get_all(
			"Journal Entry Account",
			filters={
				"parent": je.name,
				"parenttype": "Journal Entry",
				"from_template": 0,
			},
			fields=["name", "account", "party_type"],
		)

		used = set()
		for je_row in je_account_rows:
			key = (je_row.account, je_row.party_type or "")
			# Multiset match - find first unused template slot
			for tpl_idx, tpl_key in enumerate(template_keys):
				if tpl_idx in used:
					continue
				if tpl_key == key:
					frappe.db.set_value(
						"Journal Entry Account",
						je_row.name,
						"from_template",
						1,
						update_modified=False,
					)
					used.add(tpl_idx)
					matched_rows_total += 1
					break

	frappe.db.commit()
	frappe.logger().info(
		f"backfill_je_template_applied: marked {len(je_rows)} JEs template_applied=1, "
		f"matched {matched_rows_total} child rows from_template=1, "
		f"skipped {skipped_missing_template} JEs whose template no longer exists."
	)
