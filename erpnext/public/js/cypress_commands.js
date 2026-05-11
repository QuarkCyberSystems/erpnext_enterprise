// Cypress custom commands for ERPNext UI tests (WP GA-0001-01 and onward).
//
// Loaded automatically when the Cypress harness imports
// `cypress/support/e2e.js` in the Frappe fork — that file picks this up via
// a single `require("../../erpnext/erpnext/public/js/cypress_commands.js")`
// line so the helpers are available to every spec under either app.
//
// Cleanup pattern: every doc inserted by these helpers gets a marker on its
// `user_remark` field ("CYPRESS WP-XX"). Specs call `cy.cleanup_wp_test_docs`
// in `beforeEach` to wipe artifacts from prior runs — Cypress doesn't roll
// back transactions like the Python suite, so explicit cleanup is required.

const CYPRESS_MARKER = "CYPRESS WP-01";

// ───────── Journal Entry helpers (WP GA-0001-01) ─────────

Cypress.Commands.add("create_test_journal_entry", (opts = {}) => {
	const {
		company = "_Test Company",
		amount = 100,
		debit_account = "_Test Bank - _TC",
		credit_account = "_Test Cash - _TC",
		cost_center = "_Test Cost Center - _TC",
		user_remark = CYPRESS_MARKER,
		submit = true,
	} = opts;

	const args = {
		doctype: "Journal Entry",
		company,
		posting_date: Cypress.dayjs().format("YYYY-MM-DD"),
		user_remark,
		multi_currency: 0,
		accounts: [
			{
				account: debit_account,
				debit_in_account_currency: amount,
				credit_in_account_currency: 0,
				cost_center,
			},
			{
				account: credit_account,
				debit_in_account_currency: 0,
				credit_in_account_currency: amount,
				cost_center,
			},
		],
	};

	return cy.insert_doc("Journal Entry", args).then((je) => {
		if (!submit) return cy.wrap(je);
		return cy
			.call("frappe.client.submit", { doc: je })
			.then((r) => cy.wrap(r.message || je));
	});
});

Cypress.Commands.add("create_reversal_via_api", (original_name) => {
	return cy
		.call(
			"erpnext.accounts.doctype.journal_entry.journal_entry.make_reverse_journal_entry",
			{ source_name: original_name }
		)
		.then((r) => cy.wrap(r.message));
});

Cypress.Commands.add("submit_reversal_via_api", (original_name) => {
	return cy.create_reversal_via_api(original_name).then((reversal) => {
		reversal.posting_date = Cypress.dayjs().format("YYYY-MM-DD");
		reversal.user_remark = `${CYPRESS_MARKER} reversal`;
		return cy
			.call("frappe.client.insert", { doc: reversal })
			.then((r) => r.message)
			.then((inserted) =>
				cy.call("frappe.client.submit", { doc: inserted }).then((r) => r.message)
			);
	});
});

// ───────── Cleanup ─────────

Cypress.Commands.add("cleanup_wp_test_docs", () => {
	return cy
		.call("frappe.client.get_list", {
			doctype: "Journal Entry",
			filters: [["user_remark", "like", `%${CYPRESS_MARKER}%`]],
			fields: ["name", "docstatus"],
			limit_page_length: 500,
			order_by: "is_reversal desc, creation desc",
		})
		.then((r) => {
			const rows = r.message || [];
			// Cancel reversals first (so the originals' reversed_by gets cleared),
			// then cancel + delete everything.
			for (const je of rows) {
				if (je.docstatus === 1) {
					cy.call("frappe.client.cancel", {
						doctype: "Journal Entry",
						name: je.name,
					}).then(() => {}, () => {});
				}
			}
			for (const je of rows) {
				cy.call("frappe.client.delete", {
					doctype: "Journal Entry",
					name: je.name,
				}).then(() => {}, () => {});
			}
		});
});

// ───────── Assertion helpers ─────────

Cypress.Commands.add("assert_reversal_indicator", (original_name, reversal_name) => {
	cy.visit(`/app/journal-entry/${original_name}`);
	cy.get(".form-dashboard", { timeout: 15000 })
		.contains("Reversed", { timeout: 15000 })
		.should("be.visible");
	cy.get(`a[href*="/journal-entry/${reversal_name}"]`).should("exist");
});

Cypress.Commands.add("assert_no_reversal_indicator", (original_name) => {
	cy.visit(`/app/journal-entry/${original_name}`);
	cy.get(".form-dashboard", { timeout: 15000 }).should("be.visible");
	cy.get(".form-dashboard").contains("Reversed").should("not.exist");
});

// ───────── Site-wide settings toggles ─────────

Cypress.Commands.add("set_immutable_ledger", (value) => {
	return cy.call("frappe.client.set_value", {
		doctype: "Accounts Settings",
		name: "Accounts Settings",
		fieldname: "enable_immutable_ledger",
		value: value ? 1 : 0,
	});
});
