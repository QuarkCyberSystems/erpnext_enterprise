// Cypress config for ERPNext UI tests.
//
// `bench run-ui-tests erpnext` cd's into apps/erpnext and invokes cypress
// there, so cypress looks for the config in this directory. We re-export
// Frappe's master config and only override the spec glob so cypress
// discovers `**/ui_test_*.js` under erpnext/ (Frappe's config points at
// apps/frappe/cypress/integration/ which is a relative path that breaks
// when invoked from this cwd).

const path = require("path");
const frappeConfig = require("../frappe/cypress.config.js");

// `defineConfig` would re-wrap; reach into the underlying object
const baseConfig = frappeConfig.e2e || frappeConfig;

module.exports = {
	...frappeConfig,
	e2e: {
		...baseConfig,
		// Frappe's setupNodeEvents and support file paths reach into
		// ../frappe/cypress/. The bench command runs us with cwd=apps/erpnext,
		// so resolve those to absolute paths.
		supportFile: path.resolve(__dirname, "..", "frappe", "cypress", "support", "e2e.js"),
		fixturesFolder: path.resolve(__dirname, "..", "frappe", "cypress", "fixtures"),
		specPattern: ["./**/ui_test_*.js"],
		excludeSpecPattern: ["**/node_modules/**", "**/.git/**"],
		// Bump pageLoadTimeout for the WP-05+06 refactor branch — first
		// /desk load after a fresh bench-build can take longer than the
		// default 15s on this dev box.
		pageLoadTimeout: 60000,
	},
};
