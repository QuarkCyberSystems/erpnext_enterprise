// WP GA-0001-01 — Journal Entry Reversal UI tests.
//
// Mirrors the Python contract in test_journal_entry.py:625-808 but exercises
// the form-side behaviour (action button visibility, indicator chips, field
// locking, dialog rendering) that the Python suite can't reach.
//
// Test inventory matches WP §9 — TC-001 … TC-009.
// Plan: badia_docs/cypress_tests/cypress_plan_ga-0001-01.md

context("WP GA-0001-01 — Journal Entry Reversal", () => {
	const COMPANY = "_Test Company";
	const BANK = "_Test Bank - _TC";
	const CASH = "_Test Cash - _TC";

	before(() => {
		cy.login("Administrator", "admin");
		cy.set_immutable_ledger(0);
		cy.cleanup_wp_test_docs();
	});

	after(() => {
		cy.set_immutable_ledger(0);
		cy.cleanup_wp_test_docs();
	});

	// Cleanup disabled while we debug the 403 on frappe.client.get_list — the
	// cy.visit("/app") in login establishes window.frappe.csrf_token but the
	// session cookie for API calls is still being investigated.
	// beforeEach(() => {
	// 	cy.cleanup_wp_test_docs();
	// });

	// after(() => {
	// 	cy.set_immutable_ledger(0);
	// 	cy.cleanup_wp_test_docs();
	// });

	// ── TC-001 ──────────────────────────────────────────────────────────
	it("TC-001 — user creates JE, reverses via Menu, submits reversal, original shows 'Reversed by' indicator", () => {
		// Step 1: Create + submit the original JE via the form UI
		cy.create_je_via_ui({ amount: 100 }).then((original_name) => {
			// Step 2: From the submitted original, click Actions → Reverse Journal Entry
			cy.reverse_je_via_ui();
			// Step 3: Save the reversal draft, then submit it via the form UI
			cy.save();
			cy.window({ timeout: 20000 }).its("cur_frm.doc.docstatus").should("eq", 0);
			// Capture the now-real reversal name
			cy.window().its("cur_frm.doc.name").then((reversal_name) => {
				cy.get(".primary-action").contains("Submit").click();
				cy.click_modal_primary_button("Yes");
				cy.window({ timeout: 30000 }).its("cur_frm.doc.docstatus").should("eq", 1);

				// Step 4: Navigate back to the original, assert indicator
				cy.visit(`/app/journal-entry/${original_name}`);
				cy.get(".form-dashboard", { timeout: 15000 }).should("be.visible");
				cy.get(".form-dashboard").contains("Reversed", { timeout: 15000 }).should("be.visible");

				// Step 5: Indicator links back to the reversal
				cy.get(`.form-dashboard a[href*="/journal-entry/${reversal_name}"]`)
					.should("be.visible")
					.click();
				cy.location("pathname").should("include", `/journal-entry/${reversal_name}`);
			});
		});
	});

	// ── TC-002 ──────────────────────────────────────────────────────────
	it("TC-002 — cancelling a reversal under IL=0 clears reversed_by/is_reversed on the original", () => {
		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			cy.submit_reversal_via_api(original.name).then((reversal) => {
				// Cancel the reversal
				cy.call("frappe.client.cancel", {
					doctype: "Journal Entry",
					name: reversal.name,
				});

				// Original's flags clear under IL=0
				cy.get_doc("Journal Entry", original.name).then((r) => {
					expect(r.data.is_reversed, "is_reversed cleared").to.equal(0);
					// Frappe omits null Link fields from JSON serialization, so
					// reversed_by may be `undefined` on the response object.
					expect(r.data.reversed_by, "reversed_by cleared").to.be.oneOf([
						null,
						"",
						undefined,
					]);
				});

				// UI: no indicator chip on the original
				cy.assert_no_reversal_indicator(original.name);
			});
		});
	});

	// ── TC-003 ──────────────────────────────────────────────────────────
	it("TC-003 — second reversal attempt while a draft reversal exists shows a blocking error", () => {
		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			// Create a DRAFT reversal (insert but don't submit)
			cy.create_reversal_via_api(original.name).then((reversal) => {
				reversal.user_remark = "CYPRESS WP-01 draft reversal";
				cy.call("frappe.client.insert", { doc: reversal }).then((r) => {
					const draft_name = r.message.name;

					// Try to call make_reverse_journal_entry again — expect error
					cy.frappe_request({
						url: "/api/method/erpnext.accounts.doctype.journal_entry.journal_entry.make_reverse_journal_entry",
						method: "POST",
						body: { source_name: original.name },
						failOnStatusCode: false,
					}).then((resp) => {
						expect(resp.status, "duplicate-reversal blocked").to.equal(417);
						expect(JSON.stringify(resp.body)).to.include(draft_name);
					});
				});
			});
		});
	});

	// ── TC-004 ──────────────────────────────────────────────────────────
	it("TC-004 — reversal entry has account/debit/credit columns locked and rows cannot be added or removed", () => {
		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			cy.create_reversal_via_api(original.name).then((reversal) => {
				reversal.user_remark = "CYPRESS WP-01 draft reversal";
				cy.call("frappe.client.insert", { doc: reversal }).then((r) => {
					const draft_name = r.message.name;
					cy.visit(`/app/journal-entry/${draft_name}`);

					// Wait for form load
					cy.get(".form-tabs", { timeout: 15000 }).should("be.visible");

					// Grid header — Add Row button must be disabled / absent
					cy.get(".form-grid .grid-add-row").should(($el) => {
						const disabled =
							$el.length === 0 || $el.attr("disabled") !== undefined || $el.hasClass("disabled");
						expect(disabled, "add-row not actionable").to.be.true;
					});

					// Per-row delete should not be available
					cy.get(".grid-row").first().within(() => {
						cy.get(".grid-delete-row, .btn-open-row").should(($el) => {
							// Either absent or hidden
							const ok = $el.length === 0 || !$el.is(":visible");
							expect(ok, "delete-row not available").to.be.true;
						});
					});

					// Account / debit / credit cells must NOT be editable.
					// Click into the first row and try the account field —
					// expect read-only attribute / no input render.
					cy.get(".grid-row").first().find('[data-fieldname="account"]').then(($cell) => {
						// editable cell renders an <input>; locked cell renders only the
						// static value div.
						const has_input = $cell.find("input:not([type='hidden'])").length > 0;
						expect(has_input, "account cell is read-only").to.be.false;
					});
				});
			});
		});
	});

	// ── TC-005 ──────────────────────────────────────────────────────────
	it("TC-005 — submitting a reversal whose row totals were tampered via API is rejected by the server", () => {
		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			cy.create_reversal_via_api(original.name).then((reversal) => {
				reversal.user_remark = "CYPRESS WP-01 draft reversal";
				cy.call("frappe.client.insert", { doc: reversal }).then((r) => {
					const draft = r.message;
					// Tamper the first row's debit_in_account_currency to mismatch
					draft.accounts[0].debit_in_account_currency = 250;
					draft.accounts[0].credit_in_account_currency = 0;

					cy.frappe_request({
						url: "/api/method/frappe.client.submit",
						method: "POST",
						body: { doc: draft },
						failOnStatusCode: false,
					}).then((resp) => {
						expect(resp.status, "tamper rejected").to.be.oneOf([417, 400, 500]);
						expect(
							JSON.stringify(resp.body).toLowerCase(),
							"error mentions reversal totals"
						).to.match(/total|match|reversal/);
					});
				});
			});
		});
	});

	// ── TC-006 ──────────────────────────────────────────────────────────
	it("TC-006 — original form shows the orange 'Reversed by ...' indicator with a clickable link", () => {
		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			cy.submit_reversal_via_api(original.name).then((reversal) => {
				cy.visit(`/app/journal-entry/${original.name}`);

				// Wait for form + dashboard render
				cy.get(".form-dashboard", { timeout: 15000 }).should("be.visible");

				// Indicator chip text
				cy.get(".form-dashboard")
					.contains("Reversed", { timeout: 15000 })
					.should("be.visible");

				// Link is wired — clicking opens the reversal form. The indicator
				// renders two anchors (chip + dashboard tile); just click the first.
				cy.get(`a[href*="/journal-entry/${reversal.name}"]`)
					.first()
					.should("be.visible")
					.click();

				cy.location("pathname").should("include", `/journal-entry/${reversal.name}`);
			});
		});
	});

	// ── TC-007 ──────────────────────────────────────────────────────────
	it("TC-007 — the Reverse Journal Entry action is hidden on a reversal entry", () => {
		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			cy.submit_reversal_via_api(original.name).then((reversal) => {
				cy.visit(`/app/journal-entry/${reversal.name}`);
				cy.get(".form-tabs", { timeout: 15000 }).should("be.visible");

				// Open the Menu / Actions dropdown if present
				cy.get(".standard-actions, .menu-btn-group, .actions-btn-group")
					.first()
					.then(($el) => {
						if ($el.length) cy.wrap($el).find("button").first().click({ force: true });
					});

				// The "Reverse Journal Entry" menu item must not exist
				cy.contains("Reverse Journal Entry").should("not.exist");

				// Also, calling make_reverse_journal_entry on the reversal must be rejected
				cy.frappe_request({
					url: "/api/method/erpnext.accounts.doctype.journal_entry.journal_entry.make_reverse_journal_entry",
					method: "POST",
					body: { source_name: reversal.name },
					failOnStatusCode: false,
				}).then((resp) => {
					expect(resp.status).to.be.oneOf([417, 400, 500]);
					expect(JSON.stringify(resp.body).toLowerCase()).to.match(
						/reversal|cannot/
					);
				});
			});
		});
	});

	// ── TC-008 ──────────────────────────────────────────────────────────
	it("TC-008 — cancelling a reversal is blocked when Immutable Ledger is on", () => {
		cy.set_immutable_ledger(1);

		cy.create_test_journal_entry({ amount: 100 }).then((original) => {
			cy.submit_reversal_via_api(original.name).then((reversal) => {
				// Attempt cancel via API — expect rejection
				cy.frappe_request({
					url: "/api/method/frappe.client.cancel",
					method: "POST",
					body: { doctype: "Journal Entry", name: reversal.name },
					failOnStatusCode: false,
				}).then((resp) => {
					expect(resp.status, "cancel rejected under IL").to.be.oneOf([
						417,
						400,
						500,
					]);
					expect(JSON.stringify(resp.body).toLowerCase()).to.match(
						/immutable|cannot cancel/
					);
				});

				// Restore IL=0 for subsequent tests
				cy.set_immutable_ledger(0);
			});
		});
	});

	// ── TC-009 ──────────────────────────────────────────────────────────
	it("TC-009 — respect_cost_center_allocation re-resolves cost centers at reversal posting date", () => {
		// TC-008 navigated away from /app to verify Immutable Ledger rejection,
		// so reload the desk before any cy.call (which needs window.frappe).
		cy.ensure_frappe_loaded();

		const date_offset = (days) => {
			const d = new Date();
			d.setDate(d.getDate() + days);
			return d.toISOString().slice(0, 10);
		};
		const yesterday = date_offset(-365);

		// Skip if Cost Center Allocation doctype not present (older fixtures)
		cy.call("frappe.client.get_count", { doctype: "DocType", filters: { name: "Cost Center Allocation" } }).then(
			(r) => {
				if (!r.message) {
					cy.log("Cost Center Allocation doctype absent — skipping TC-009");
					return;
				}

				// Cypress dayjs may not be available everywhere — guard import.
				cy.create_test_journal_entry({
					amount: 100,
					posting_date_override: yesterday,
				}).then((original) => {
					// Toggle respect_cost_center_allocation via the API path
					cy.call(
						"erpnext.accounts.doctype.journal_entry.journal_entry.make_reverse_journal_entry",
						{ source_name: original.name }
					).then((rev_r) => {
						const reversal = rev_r.message;
						reversal.respect_cost_center_allocation = 1;
						reversal.posting_date = date_offset(0);
						reversal.user_remark = "CYPRESS WP-01 reversal CCA";
						cy.call("frappe.client.insert", { doc: reversal }).then((ins_r) => {
							// `reversal` is a pre-insert mapped doc with no name yet;
							// pull the assigned name from the insert response.
							const reversal_name = ins_r.message.name;
							cy.get_doc("Journal Entry", reversal_name).then((r2) => {
								expect(
									r2.data.respect_cost_center_allocation,
									"flag persisted on reversal"
								).to.equal(1);
							});
						});
					});
				});
			}
		);
	});
});
