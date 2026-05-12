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

// Cypress 13 does not ship Cypress.dayjs. Use plain JS so we don't take a
// runtime dep on a date library. `offset_days` shifts by N (can be negative).
function today_str(offset_days = 0) {
	const d = new Date();
	d.setDate(d.getDate() + offset_days);
	return d.toISOString().slice(0, 10);
}

// Override the Frappe-side cy.login with a simpler version for our wp-test
// site: skip cy.session (which adds validation hops that 401 on first use),
// send form-urlencoded so Frappe's auth pipeline picks up usr/pwd from
// form_dict directly, and tolerate the 200 response without a redirect.
Cypress.Commands.overwrite("login", (_originalFn, email, password) => {
	if (!email) email = Cypress.config("testUser") || "Administrator";
	if (!password) password = Cypress.env("adminPassword") || "admin";
	return cy
		.request({
			url: "/api/method/login",
			method: "POST",
			form: true, // urlencoded — matches what curl POSTs to /api/method/login
			body: { usr: email, pwd: password },
			failOnStatusCode: true,
		})
		.then(() => {
			// Visit /app so window.frappe + csrf_token get initialized. cy.call
			// reads frappe.csrf_token from window — without a desk page load it
			// fails with "property: frappe.csrf_token does not exist".
			cy.visit("/app");
			cy.window({ timeout: 30000 }).its("frappe.csrf_token");
		});
});

// Wrap cy.request with CSRF + session cookie handling. Frappe rejects API
// calls without a valid X-Frappe-CSRF-Token header (csrftokenerror).
Cypress.Commands.add("frappe_request", (opts) => {
	return cy
		.window({ timeout: 30000 })
		.its("frappe.csrf_token")
		.then((csrf) => {
			return cy.request({
				...opts,
				headers: { ...(opts.headers || {}), "X-Frappe-CSRF-Token": csrf },
			});
		});
});

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
		posting_date: today_str(),
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
		.then((r) => {
			// make_reverse_journal_entry leaves posting_date blank; fill it so
			// subsequent insert() doesn't trip on MandatoryError.
			const reversal = r.message;
			reversal.posting_date = today_str();
			reversal.user_remark = reversal.user_remark || `${CYPRESS_MARKER} draft reversal`;
			return cy.wrap(reversal);
		});
});

Cypress.Commands.add("submit_reversal_via_api", (original_name) => {
	return cy.create_reversal_via_api(original_name).then((reversal) => {
		reversal.posting_date = today_str();
		reversal.user_remark = `${CYPRESS_MARKER} reversal`;
		return cy
			.call("frappe.client.insert", { doc: reversal })
			.then((r) => r.message)
			.then((inserted) =>
				cy.call("frappe.client.submit", { doc: inserted }).then((r) => r.message)
			);
	});
});

// ───────── UI-flow helpers (Pure-UI tests, WP GA-0001-01) ─────────
//
// `cy.create_je_via_ui` clicks through the full user flow: New form → fill
// header → fill two account rows → Save → Submit → confirm dialog. Yields
// the new doc name once the form lands on the submitted state.

Cypress.Commands.add("create_je_via_ui", (opts = {}) => {
	const {
		company = "_Test Company",
		amount = 100,
		debit_account = "_Test Bank - _TC",
		credit_account = "_Test Cash - _TC",
		cost_center = "_Test Cost Center - _TC",
		posting_date = today_str(),
		submit = true,
	} = opts;

	cy.visit("/app/journal-entry/new?journal_entry_type=Journal Entry");
	cy.get(".form-tabs", { timeout: 30000 }).should("be.visible");

	// Header fields. user_remark is hidden in the form schema; skip it.
	cy.fill_field("posting_date", posting_date, "Date").blur();
	cy.fill_field("company", company, "Link");

	// Populate the accounts grid via the form's own JS model — same path
	// ERPNext uses when users paste rows or import from Excel. We're still
	// inside the form context (no API call); save/submit happen via UI clicks
	// below. This avoids the auto-row-open + dropdown choreography that makes
	// per-cell fill_table_field unreliable on the JE grid.
	cy.window().then((win) => {
		const frm = win.cur_frm;
		frm.doc.accounts = [];
		frm.doc.accounts.push({
			account: debit_account,
			debit_in_account_currency: amount,
			credit_in_account_currency: 0,
			cost_center,
		});
		frm.doc.accounts.push({
			account: credit_account,
			debit_in_account_currency: 0,
			credit_in_account_currency: amount,
			cost_center,
		});
		frm.refresh_field("accounts");
	});

	cy.save();
	cy.get(".title-area .indicator-pill", { timeout: 20000 }).should(($el) => {
		const t = $el.text();
		expect(t).to.match(/Draft|Not Submitted/);
	});

	if (!submit) {
		// Capture doc name from URL
		return cy.location("pathname").then((p) => {
			const name = decodeURIComponent(p.split("/").pop());
			return cy.wrap(name);
		});
	}

	cy.get(".primary-action").contains("Submit").click();
	cy.click_modal_primary_button("Yes");
	// Assert via the form's own model rather than the indicator pill text
	// (the pill text in this Frappe version sometimes shows the doctype name).
	cy.window({ timeout: 30000 }).its("cur_frm.doc.docstatus").should("eq", 1);

	return cy.location("pathname").then((p) => {
		const name = decodeURIComponent(p.split("/").pop());
		return cy.wrap(name);
	});
});

// Clicks Menu → Reverse Journal Entry on an already-open submitted JE form.
// Yields the new draft reversal's doc name once it lands.
Cypress.Commands.add("reverse_je_via_ui", () => {
	// "Reverse Journal Entry" is a custom button under the Actions group.
	// frm.add_custom_button doesn't set data-label, so we click by visible text.
	cy.findByRole("button", { name: "Actions" }).click();
	cy.get(".dropdown-menu:visible").contains("Reverse Journal Entry").click({ force: true });
	// Frappe redirects to the new draft (URL is /desk/ or /app/, name is a
	// temp `new-...` ID). Wait for the form to load as a fresh draft.
	cy.location("pathname", { timeout: 30000 }).should("match", /\/(desk|app)\/journal-entry\/[^/]+$/);
	cy.get(".form-tabs", { timeout: 20000 }).should("be.visible");
	cy.window({ timeout: 20000 }).its("cur_frm.doc.docstatus").should("eq", 0);
	// Return nothing — the spec must save first before we can capture a real doc name.
});

// ───────── Cleanup ─────────

// Cleanup is sequenced via Cypress's promise chain. Cancel reversals first
// (clears their originals' reversed_by), then cancel + delete the rest.
// failOnStatusCode:false so already-cancelled or linked docs don't abort the loop.
function _delete_one(name) {
	return cy.request({
		url: "/api/method/frappe.client.delete",
		method: "POST",
		body: { doctype: "Journal Entry", name },
		headers: { "X-Frappe-CSRF-Token": "token" },
		failOnStatusCode: false,
	});
}

function _cancel_one(name) {
	return cy.request({
		url: "/api/method/frappe.client.cancel",
		method: "POST",
		body: { doctype: "Journal Entry", name },
		headers: { "X-Frappe-CSRF-Token": "token" },
		failOnStatusCode: false,
	});
}

// Make sure we're on a desk page so `window.frappe` + csrf_token exist before
// firing cy.call / cy.frappe_request. Cheap no-op if already loaded.
Cypress.Commands.add("ensure_frappe_loaded", () => {
	return cy.window().then((win) => {
		if (!win.frappe || !win.frappe.csrf_token) {
			cy.visit("/app");
			cy.window({ timeout: 30000 }).its("frappe.csrf_token");
		}
	});
});

Cypress.Commands.add("cleanup_wp_test_docs", () => {
	cy.ensure_frappe_loaded();
	return cy
		.window()
		.its("frappe.csrf_token")
		.then((csrf) => {
			return cy
				.request({
					url: "/api/method/frappe.client.get_list",
					method: "POST",
					body: {
						doctype: "Journal Entry",
						filters: [["user_remark", "like", `%${CYPRESS_MARKER}%`]],
						fields: ["name", "docstatus", "is_reversal"],
						limit_page_length: 500,
						order_by: "is_reversal desc, creation desc",
					},
					headers: { "X-Frappe-CSRF-Token": csrf },
					failOnStatusCode: false,
				})
				.then((resp) => {
					const rows = (resp.body && resp.body.message) || [];
					// Two passes so reversals get cancelled before their originals.
					let chain = cy.wrap(null, { log: false });
					for (const je of rows) {
						if (je.docstatus === 1) {
							chain = chain.then(() => _cancel_one(je.name));
						}
					}
					for (const je of rows) {
						chain = chain.then(() => _delete_one(je.name));
					}
					return chain;
				});
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

// ───────── WP GA-0001-03 (Payment Reconciliation Entry) helpers ─────────
//
// PRE creation requires `book_advance_payments_in_separate_party_account` on
// the company plus the two default advance accounts. The spec's before-hook
// flips these on and the after-hook flips them off so we don't pollute the
// dev site's company config.

const WP03_MARKER = "CYPRESS WP-03";
const WP03_COMPANY = "_Test Company";
const WP03_CUSTOMER = "_Test Customer";
const WP03_ITEM = "_Test Item";
const WP03_DEBIT_TO = "Debtors - _TC";
const WP03_PAID_TO = "Cash - _TC";
const WP03_INCOME_ACC = "Sales - _TC";
const WP03_COST_CENTER = "_Test Cost Center - _TC";
const WP03_ADVANCE_RECEIVED = "Advance Received - _TC";
const WP03_ADVANCE_PAID = "Advance Paid - _TC";

Cypress.Commands.add("setup_wp03_company_defaults", () => {
	cy.call("frappe.client.set_value", {
		doctype: "Company",
		name: WP03_COMPANY,
		fieldname: {
			default_advance_received_account: WP03_ADVANCE_RECEIVED,
			default_advance_paid_account: WP03_ADVANCE_PAID,
			book_advance_payments_in_separate_party_account: 1,
		},
	});
	cy.set_immutable_ledger(1);
	// Standard Selling/Buying price lists on this site are in AED; company is
	// INR. Without an exchange rate row, the SI form opens an "Unable to find
	// exchange rate" dialog that blocks save. Stamp a 1:1 rate for today so
	// the form proceeds. Cypress runs in dev, no business impact.
	const today = today_str();
	cy.frappe_request({
		url: "/api/method/frappe.client.get_list",
		method: "POST",
		body: {
			doctype: "Currency Exchange",
			filters: { from_currency: "AED", to_currency: "INR", date: today },
			fields: ["name"],
			limit_page_length: 1,
		},
	}).then((resp) => {
		const rows = (resp.body && resp.body.message) || [];
		if (rows.length === 0) {
			cy.insert_doc("Currency Exchange", {
				doctype: "Currency Exchange",
				from_currency: "AED",
				to_currency: "INR",
				exchange_rate: 1.0,
				for_selling: 1,
				for_buying: 1,
				date: today,
			});
		}
	});
});

Cypress.Commands.add("teardown_wp03_company_defaults", () => {
	cy.call("frappe.client.set_value", {
		doctype: "Company",
		name: WP03_COMPANY,
		fieldname: { book_advance_payments_in_separate_party_account: 0 },
	});
	cy.set_immutable_ledger(0);
});

// Insert + submit a Sales Invoice via API. Yields the SI doc dict.
Cypress.Commands.add("create_test_si_via_api", (opts = {}) => {
	const { amount = 100, customer = WP03_CUSTOMER } = opts;
	return cy
		.insert_doc("Sales Invoice", {
			doctype: "Sales Invoice",
			company: WP03_COMPANY,
			customer,
			debit_to: WP03_DEBIT_TO,
			currency: "INR",
			posting_date: today_str(),
			remarks: `${WP03_MARKER} SI`,
			items: [
				{
					item_code: WP03_ITEM,
					qty: 1,
					rate: amount,
					income_account: WP03_INCOME_ACC,
					cost_center: WP03_COST_CENTER,
				},
			],
		})
		.then((si) => cy.call("frappe.client.submit", { doc: si }).then((r) => r.message));
});

// Insert + submit a Payment Entry receiving from a Customer. Yields the PE.
Cypress.Commands.add("create_test_pe_via_api", (opts = {}) => {
	const { amount = 100, customer = WP03_CUSTOMER } = opts;
	return cy
		.insert_doc("Payment Entry", {
			doctype: "Payment Entry",
			payment_type: "Receive",
			company: WP03_COMPANY,
			party_type: "Customer",
			party: customer,
			paid_from: WP03_DEBIT_TO,
			paid_to: WP03_PAID_TO,
			paid_amount: amount,
			received_amount: amount,
			reference_no: WP03_MARKER,
			reference_date: today_str(),
			posting_date: today_str(),
		})
		.then((pe) => cy.call("frappe.client.submit", { doc: pe }).then((r) => r.message));
});

// Drive the Payment Reconciliation tool's whitelisted methods to reconcile a
// PE against an SI. PR is a transient tool doctype — invoke its methods via
// `frappe.handler.run_doc_method` which accepts a serialized doc + method
// name + args. Going through cy.frappe_request keeps error handling in one
// place (frappe.call's error callback rejecting trips Cypress' command
// chain with an "undefined onFail" crash).
function _run_doc_method(doc, method, args) {
	return cy
		.frappe_request({
			url: "/api/method/run_doc_method",
			method: "POST",
			body: {
				docs: JSON.stringify(doc),
				method,
				args: args ? JSON.stringify(args) : undefined,
			},
			failOnStatusCode: false,
		})
		.then((resp) => {
			if (resp.status !== 200 && resp.status !== 201) {
				cy.log(`run_doc_method ${method} body = ${JSON.stringify(resp.body).slice(0, 600)}`);
			}
			expect(resp.status, `run_doc_method ${method}`).to.be.oneOf([200, 201]);
			// Server echoes the modified doc back in `docs[0]`.
			return resp.body.docs ? resp.body.docs[0] : doc;
		});
}

Cypress.Commands.add("reconcile_pe_against_si_via_api", () => {
	const pr_doc = {
		doctype: "Payment Reconciliation",
		company: WP03_COMPANY,
		party_type: "Customer",
		party: WP03_CUSTOMER,
		receivable_payable_account: WP03_DEBIT_TO,
		default_advance_account: WP03_ADVANCE_RECEIVED,
	};
	return _run_doc_method(pr_doc, "get_unreconciled_entries").then((pr1) => {
		// allocate_entries(self, args) — body is the args dict directly,
		// not nested under {args: ...}.
		const args = {
			invoices: (pr1.invoices || []).map((i) => ({ ...i })),
			payments: (pr1.payments || []).map((p) => ({ ...p })),
		};
		return _run_doc_method(pr1, "allocate_entries", args).then((pr2) =>
			_run_doc_method(pr2, "reconcile")
		);
	});
});

// ───────── WP GA-0001-04 (Journal Entry Template) helpers ─────────

// Insert a Journal Entry Template via API. Used by the spec's before-hook
// so each test can drive the from_template flow against a known fixture.
Cypress.Commands.add("create_test_je_template", (opts = {}) => {
	const {
		title,
		allow_additional_accounts = 0,
		lock_on_apply = 1,
		// Three generic non-party accounts so submits don't trip JE's
		// "Party Type/Party required for Receivable/Payable" validation.
		accounts = [
			{ account: "_Test Bank - _TC", cost_center: "_Test Cost Center - _TC" },
			{ account: "_Test Cash - _TC", cost_center: "_Test Cost Center - _TC" },
			{ account: "Prepaid Expenses - _TC", cost_center: "_Test Cost Center - _TC" },
		],
	} = opts;
	return cy.insert_doc("Journal Entry Template", {
		doctype: "Journal Entry Template",
		template_title: title,
		company: "_Test Company",
		voucher_type: "Journal Entry",
		multi_currency: 0,
		is_opening: "No",
		// naming_series is reqd=1 with options=None on this doctype — autoname
		// is field:template_title, but the column still must be non-null.
		naming_series: "JE-",
		lock_on_apply,
		allow_additional_accounts,
		accounts: accounts.map((a) => ({
			account: a.account,
			cost_center: a.cost_center,
		})),
	});
});

// Cleanup any WP-04/WP-05 test templates + the JEs created from them.
// The filter matches `CYPRESS-WP0%` to catch both WP04 and WP05 prefixes
// without forcing the spec authors to maintain a per-WP cleanup helper.
Cypress.Commands.add("cleanup_wp04_test_docs", () => {
	cy.ensure_frappe_loaded();
	let chain = cy.wrap(null, { log: false });
	// JEs first (so the template isn't link-blocked by an open JE), then templates.
	const stages = [
		["Journal Entry", [["from_template", "like", `CYPRESS-WP0%`]]],
		["Journal Entry Template", [["template_title", "like", `CYPRESS-WP0%`]]],
	];
	for (const [doctype, filters] of stages) {
		chain = chain.then(() =>
			cy
				.window()
				.its("frappe.csrf_token")
				.then((csrf) =>
					cy.request({
						url: "/api/method/frappe.client.get_list",
						method: "POST",
						body: { doctype, filters, fields: ["name", "docstatus"], limit_page_length: 500 },
						headers: { "X-Frappe-CSRF-Token": csrf },
						failOnStatusCode: false,
					})
				)
				.then((resp) => {
					const rows = (resp.body && resp.body.message) || [];
					let sub = cy.wrap(null, { log: false });
					for (const row of rows) {
						if (row.docstatus === 1) {
							sub = sub.then(() =>
								cy.frappe_request({
									url: "/api/method/frappe.client.cancel",
									method: "POST",
									body: { doctype, name: row.name },
									failOnStatusCode: false,
								})
							);
						}
					}
					for (const row of rows) {
						sub = sub.then(() =>
							cy.frappe_request({
								url: "/api/method/frappe.client.delete",
								method: "POST",
								body: { doctype, name: row.name },
								failOnStatusCode: false,
							})
						);
					}
					return sub;
				})
		);
	}
	return chain;
});

// ───────── WP GA-0001-05+06 (Auto Repeat Enhancements) helpers ─────────
//
// The auto-reversal flow on JE only fires when from_template + template_applied
// + enable_auto_reversal all =1, so these helpers extend the WP-04 template
// helpers to add auto-reversal config + drive the JE-from-template flow.

// Insert a JE Template with auto-reversal config. Variant of
// create_test_je_template; we override the auto-reversal fields on top of
// the WP-04 template body so the WP-04 helper stays minimal.
Cypress.Commands.add("create_test_je_template_with_auto_reversal", (opts = {}) => {
	const {
		title,
		auto_reverse_on = "First Day of Next Month",
		auto_reverse_date = null,
		reversal_tax_mode = "Use Original",
		reversal_cost_center_mode = "Use Original",
		accounts = [
			{ account: "_Test Bank - _TC", cost_center: "_Test Cost Center - _TC" },
			{ account: "_Test Cash - _TC", cost_center: "_Test Cost Center - _TC" },
		],
	} = opts;
	return cy.insert_doc("Journal Entry Template", {
		doctype: "Journal Entry Template",
		template_title: title,
		company: "_Test Company",
		voucher_type: "Journal Entry",
		multi_currency: 0,
		is_opening: "No",
		naming_series: "JE-",
		lock_on_apply: 1,
		allow_additional_accounts: 0,
		enable_auto_reversal: 1,
		auto_reverse_on,
		auto_reverse_date,
		reversal_exchange_rate_type: "Original Rate",
		reversal_tax_mode,
		reversal_cost_center_mode,
		auto_submit_reversal: 0,
		accounts: accounts.map((a) => ({ account: a.account, cost_center: a.cost_center })),
	});
});

// Cancel + delete every Auto Repeat doc whose reference_doctype is Journal
// Entry. WP-05+06 only creates Auto Repeats from JE submit, so this catches
// just the test artifacts.
Cypress.Commands.add("cleanup_wp0506_auto_repeats", () => {
	cy.ensure_frappe_loaded();
	return cy
		.frappe_request({
			url: "/api/method/frappe.client.get_list",
			method: "POST",
			body: {
				doctype: "Auto Repeat",
				filters: { reference_doctype: "Journal Entry", repeat_type: "Reversal" },
				fields: ["name", "docstatus"],
				limit_page_length: 500,
			},
			failOnStatusCode: false,
		})
		.then((resp) => {
			const rows = (resp.body && resp.body.message) || [];
			let chain = cy.wrap(null, { log: false });
			for (const row of rows) {
				if (row.docstatus === 1) {
					chain = chain.then(() =>
						cy.frappe_request({
							url: "/api/method/frappe.client.cancel",
							method: "POST",
							body: { doctype: "Auto Repeat", name: row.name },
							failOnStatusCode: false,
						})
					);
				}
			}
			for (const row of rows) {
				chain = chain.then(() =>
					cy.frappe_request({
						url: "/api/method/frappe.client.delete",
						method: "POST",
						body: { doctype: "Auto Repeat", name: row.name },
						failOnStatusCode: false,
					})
				);
			}
			return chain;
		});
});

// Best-effort cleanup for WP-03 docs created by the spec. Cancel reversal PREs
// first, then originals, then Unreconcile Payment docs, then SI/PE.
Cypress.Commands.add("cleanup_wp03_test_docs", () => {
	cy.ensure_frappe_loaded();
	const types_and_filters = [
		["Payment Reconciliation Entry", [["is_reversal", "=", 1]]],
		["Payment Reconciliation Entry", [["is_reversal", "=", 0]]],
		["Unreconcile Payment", [["company", "=", WP03_COMPANY]]],
		["Payment Entry", [["reference_no", "=", WP03_MARKER]]],
		["Sales Invoice", [["remarks", "like", `%${WP03_MARKER}%`]]],
	];
	let chain = cy.wrap(null, { log: false });
	for (const [doctype, filters] of types_and_filters) {
		chain = chain.then(() =>
			cy
				.window()
				.its("frappe.csrf_token")
				.then((csrf) =>
					cy.request({
						url: "/api/method/frappe.client.get_list",
						method: "POST",
						body: { doctype, filters, fields: ["name", "docstatus"], limit_page_length: 500 },
						headers: { "X-Frappe-CSRF-Token": csrf },
						failOnStatusCode: false,
					})
				)
				.then((resp) => {
					const rows = (resp.body && resp.body.message) || [];
					let sub = cy.wrap(null, { log: false });
					for (const row of rows) {
						if (row.docstatus === 1) {
							sub = sub.then(() =>
								cy.frappe_request({
									url: "/api/method/frappe.client.cancel",
									method: "POST",
									body: { doctype, name: row.name },
									failOnStatusCode: false,
								})
							);
						}
					}
					for (const row of rows) {
						sub = sub.then(() =>
							cy.frappe_request({
								url: "/api/method/frappe.client.delete",
								method: "POST",
								body: { doctype, name: row.name },
								failOnStatusCode: false,
							})
						);
					}
					return sub;
				})
		);
	}
	return chain;
});
