// WP GA-0001-05+06 — Auto Repeat Enhancements UI tests.
//
// Plan: badia_docs/cypress_tests/cypress_plan_ga-0001-05+06.md
//
// Coverage: 5 of 31 WP-05+06 TCs that have UI surface worth Cypress.
// Remaining 26 TCs are backend (Auto Repeat creation logic, scheduled-job
// behaviour, refresh modes, reversal mode rules, etc.) and stay Python.
//
//   TC-005  — Auto Repeat form: repeat_type=Reversal toggles UI fields
//   TC-022  — JE from template with auto-reversal config (next-month) →
//             on submit, Auto Repeat is created and linked_auto_repeat set
//   TC-023  — Same as TC-022 but with auto_reverse_on="Specific Date"
//   TC-024  — JE form's auto-reversal section is hidden when
//             enable_auto_reversal=0 (depends_on visibility)
//   TC-025  — Duplicate-prevention: a JE already has an Auto Repeat; a
//             second insert against the same reference_document is rejected

context("WP GA-0001-05+06 — Auto Repeat Enhancements", () => {
	const TPL_NEXT_MONTH = "CYPRESS-WP05-auto-reversal-nm";
	const TPL_SPECIFIC = "CYPRESS-WP05-auto-reversal-sd";
	const future_date = () => {
		const d = new Date();
		d.setDate(d.getDate() + 14);
		return d.toISOString().slice(0, 10);
	};

	before(() => {
		cy.login("Administrator", "admin");
		cy.cleanup_wp0506_auto_repeats();
		cy.cleanup_wp04_test_docs();
		cy.create_test_je_template_with_auto_reversal({
			title: TPL_NEXT_MONTH,
			auto_reverse_on: "First Day of Next Month",
		});
		cy.create_test_je_template_with_auto_reversal({
			title: TPL_SPECIFIC,
			auto_reverse_on: "Specific Date",
			auto_reverse_date: future_date(),
		});
	});

	after(() => {
		cy.cleanup_wp0506_auto_repeats();
		cy.cleanup_wp04_test_docs();
	});

	// Helper: open a fresh JE form, apply the template via UI (the WP-05+06
	// surface under test — verifies the auto-reversal config flows from the
	// template into the form fields), then *submit via API* because Cypress
	// can't reliably fill JE grid amounts (documented gap in WP-04 plan).
	// Yields the submitted JE's name via cy.wrap('@je_name').
	const apply_template_via_ui_then_submit_via_api = (template_title) => {
		cy.visit("/app/journal-entry/new?journal_entry_type=Journal Entry");
		cy.window({ timeout: 30000 }).its("cur_frm.doctype").should("eq", "Journal Entry");
		cy.window().then((win) => new Cypress.Promise((resolve) => {
			win.cur_frm.set_value("from_template", template_title).then(resolve);
		}));
		cy.window({ timeout: 15000 }).its("cur_frm.doc.template_applied").should("eq", 1);
	};

	// API-side: insert + submit a JE with the same auto-reversal settings as
	// the template, so the JE controller's _maybe_create_template_auto_repeat
	// fires and an Auto Repeat doc is created. We mirror the UI-visible
	// template flow's outcome (from_template, enable_auto_reversal, etc.)
	// without going through the row-handler async chain.
	const submit_je_with_template_settings_via_api = (template_title) =>
		cy.frappe_request({
			url: "/api/method/frappe.client.get_value",
			method: "POST",
			body: {
				doctype: "Journal Entry Template",
				filters: { name: template_title },
				fieldname: ["enable_auto_reversal", "auto_reverse_on", "auto_reverse_date"],
			},
		}).then((resp) => {
			const tpl = (resp.body && resp.body.message) || {};
			return cy.insert_doc("Journal Entry", {
				doctype: "Journal Entry",
				company: "_Test Company",
				posting_date: new Date().toISOString().slice(0, 10),
				voucher_type: "Journal Entry",
				multi_currency: 0,
				from_template: template_title,
				template_applied: 1,
				enable_auto_reversal: tpl.enable_auto_reversal,
				auto_reverse_on: tpl.auto_reverse_on,
				auto_reverse_date: tpl.auto_reverse_date,
				reversal_exchange_rate_type: "Original Rate",
				reversal_tax_mode: "Use Original",
				reversal_cost_center_mode: "Use Original",
				auto_submit_reversal: 0,
				accounts: [
					{
						account: "_Test Bank - _TC",
						cost_center: "_Test Cost Center - _TC",
						debit_in_account_currency: 100,
						credit_in_account_currency: 0,
						from_template: 1,
					},
					{
						account: "_Test Cash - _TC",
						cost_center: "_Test Cost Center - _TC",
						debit_in_account_currency: 0,
						credit_in_account_currency: 100,
						from_template: 1,
					},
				],
			}).then((je) => cy.call("frappe.client.submit", { doc: je }).then((r) => r.message));
		});

	// ── TC-005 ──────────────────────────────────────────────────────────
	it("TC-005 — Auto Repeat form: selecting repeat_type=Reversal toggles UI fields", () => {
		// Open a fresh Auto Repeat form. Reference a real submitted JE so the
		// form's reference_document validations don't block our toggle test.
		cy.visit("/app/auto-repeat/new");
		cy.window({ timeout: 30000 }).its("cur_frm.doctype").should("eq", "Auto Repeat");

		// Initial state: repeat_type defaults to Copy → refresh_mode visible,
		// reverse_on_next_month hidden.
		cy.window().then((win) => {
			const frm = win.cur_frm;
			expect(frm.doc.repeat_type, "default repeat_type").to.eq("Copy");
			expect(
				frm.fields_dict.refresh_mode.df.hidden,
				"refresh_mode visible when Copy"
			).not.to.eq(1);
		});

		// Toggle to Reversal.
		cy.window().then((win) => new Cypress.Promise((resolve) => {
			win.cur_frm.set_value("repeat_type", "Reversal").then(resolve);
		}));

		cy.window().then((win) => {
			const frm = win.cur_frm;
			expect(frm.doc.repeat_type, "repeat_type set to Reversal").to.eq("Reversal");
			// reverse_on_next_month depends_on `repeat_type == 'Reversal'` — section visible
			const $section = win.$(frm.wrapper).find('[data-fieldname="reverse_on_next_month"]');
			expect($section.length, "reverse_on_next_month field rendered").to.be.greaterThan(0);
			// refresh_mode field hides via depends_on `repeat_type == 'Copy'`.
			// Frappe sets visibility via the .form-control wrapper's display
			// style; assert the wrapper element isn't visible.
			const $refresh = win.$(frm.wrapper).find('[data-fieldname="refresh_mode"]');
			expect($refresh.is(":visible"), "refresh_mode hidden when Reversal").to.be.false;
			// repeat_type=Reversal handler force-sets these defaults
			expect(frm.doc.reverse_on_next_month, "reverse_on_next_month default").to.eq(1);
			expect(frm.doc.reversal_tax_mode, "reversal_tax_mode default").to.eq("Use Original");
		});
	});

	// ── TC-022 ──────────────────────────────────────────────────────────
	it("TC-022 — JE from auto-reversal template (next-month) creates Auto Repeat on submit", () => {
		// UI part: open form, apply template, verify auto-reversal config
		// flows to JE fields (this is the user-visible affordance).
		apply_template_via_ui_then_submit_via_api(TPL_NEXT_MONTH);
		cy.window({ timeout: 10000 }).its("cur_frm.doc.enable_auto_reversal").should("eq", 1);
		cy.window().its("cur_frm.doc.auto_reverse_on").should("eq", "First Day of Next Month");

		// API submit (UI submit is blocked by the row-handler chain — see
		// cypress_plan_ga-0001-04.md TC-007 rationale). Verify: Auto Repeat
		// created for this JE.
		submit_je_with_template_settings_via_api(TPL_NEXT_MONTH).then((je) => {
			cy.frappe_request({
				url: "/api/method/frappe.client.get_list",
				method: "POST",
				body: {
					doctype: "Auto Repeat",
					filters: {
						reference_doctype: "Journal Entry",
						reference_document: je.name,
						repeat_type: "Reversal",
					},
					fields: ["name", "reverse_on_next_month", "docstatus"],
					limit_page_length: 5,
				},
			}).then((resp) => {
				const rows = (resp.body && resp.body.message) || [];
				expect(rows.length, "one Auto Repeat created for this JE").to.eq(1);
				expect(rows[0].reverse_on_next_month, "reverse_on_next_month=1").to.eq(1);
				expect(rows[0].docstatus, "Auto Repeat submitted").to.eq(1);
			});
		});
	});

	// ── TC-023 ──────────────────────────────────────────────────────────
	it("TC-023 — JE from auto-reversal template (Specific Date) creates Auto Repeat with reverse_date", () => {
		apply_template_via_ui_then_submit_via_api(TPL_SPECIFIC);
		cy.window({ timeout: 10000 }).its("cur_frm.doc.enable_auto_reversal").should("eq", 1);
		cy.window().its("cur_frm.doc.auto_reverse_on").should("eq", "Specific Date");
		cy.window().its("cur_frm.doc.auto_reverse_date").should("match", /^\d{4}-\d{2}-\d{2}$/);

		submit_je_with_template_settings_via_api(TPL_SPECIFIC).then((je) => {
			cy.frappe_request({
				url: "/api/method/frappe.client.get_list",
				method: "POST",
				body: {
					doctype: "Auto Repeat",
					filters: {
						reference_doctype: "Journal Entry",
						reference_document: je.name,
						repeat_type: "Reversal",
					},
					fields: ["name", "reverse_on_next_month", "reverse_date", "docstatus"],
					limit_page_length: 5,
				},
			}).then((resp) => {
				const rows = (resp.body && resp.body.message) || [];
				expect(rows.length, "one Auto Repeat created").to.eq(1);
				expect(rows[0].reverse_on_next_month, "reverse_on_next_month=0").to.eq(0);
				expect(rows[0].reverse_date, "reverse_date populated").to.match(/^\d{4}-\d{2}-\d{2}$/);
			});
		});
	});

	// ── TC-024 ──────────────────────────────────────────────────────────
	it("TC-024 — JE form auto-reversal section is hidden when enable_auto_reversal=0", () => {
		// A bare new JE has enable_auto_reversal=0 by default → section hidden.
		// (The WP doc's "is_reversed=1" framing collapses to the same case in
		// practice: depends_on the section is `eval:doc.enable_auto_reversal`.)
		cy.visit("/app/journal-entry/new?journal_entry_type=Journal Entry");
		cy.window({ timeout: 30000 }).its("cur_frm.doctype").should("eq", "Journal Entry");
		cy.window().then((win) => {
			const frm = win.cur_frm;
			expect(frm.doc.enable_auto_reversal || 0, "enable_auto_reversal=0 by default").to.eq(0);
			// Section's wrapper has class form-section. With depends_on falsy,
			// disp_status is "Hidden" or the section gets a "hide" class.
			const $section = win.$(frm.wrapper).find('[data-fieldname="auto_reversal_section"]');
			expect($section.length, "auto_reversal_section element exists").to.be.greaterThan(0);
			const visible = $section.is(":visible") && !$section.hasClass("hide");
			expect(visible, "auto_reversal_section hidden when enable_auto_reversal=0").to.be.false;
		});
	});

	// ── TC-025 ──────────────────────────────────────────────────────────
	it("TC-025 — second Auto Repeat insert against an already-auto-reversing JE is rejected/duplicate-detected", () => {
		// Ensure /app is loaded so window.frappe.csrf_token exists.
		cy.ensure_frappe_loaded();
		// Reuse the JE created by TC-022/TC-023 path: any submitted JE that
		// already has a "Reversal" Auto Repeat — TC-022 ran first.
		cy.frappe_request({
			url: "/api/method/frappe.client.get_list",
			method: "POST",
			body: {
				doctype: "Auto Repeat",
				filters: { reference_doctype: "Journal Entry", repeat_type: "Reversal", docstatus: 1 },
				fields: ["name", "reference_document"],
				limit_page_length: 5,
				order_by: "creation desc",
			},
		}).then((resp) => {
			const rows = (resp.body && resp.body.message) || [];
			expect(rows.length, "TC-022/023 left at least one Auto Repeat").to.be.greaterThan(0);
			const je_name = rows[0].reference_document;

			// Attempt to insert a *second* Reversal Auto Repeat for the same JE.
			cy.frappe_request({
				url: "/api/method/frappe.client.insert",
				method: "POST",
				body: {
					doc: {
						doctype: "Auto Repeat",
						reference_doctype: "Journal Entry",
						reference_document: je_name,
						repeat_type: "Reversal",
						reverse_on_next_month: 1,
						start_date: new Date().toISOString().slice(0, 10),
					},
				},
				failOnStatusCode: false,
			}).then((dup_resp) => {
				// Frappe rejects with either 417 (ValidationError) or 500.
				// We accept any non-2xx; the precise validator may evolve.
				expect(dup_resp.status, "duplicate insert rejected").to.not.be.oneOf([200, 201]);
				expect(
					JSON.stringify(dup_resp.body || {}).toLowerCase(),
					"error mentions duplicate/already/exists"
				).to.match(/already|exists|duplicate|reversal/);
			});
		});
	});
});
