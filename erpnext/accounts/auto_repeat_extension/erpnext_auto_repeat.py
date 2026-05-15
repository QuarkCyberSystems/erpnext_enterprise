# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt
"""ERPNext-side override of frappe's Auto Repeat doctype controller.

WP GA-0001-05+06 originally added ~700 lines of accounting-specific behavior
directly to frappe.automation.auto_repeat. After the upstream-shape refactor,
the requirement tightened to: frappe must remain *completely untouched*
upstream-equivalent. The entire WP-05+06 contribution now lives ERPNext-side:

  - `repeat_type` (Copy / Reversal) + source-validation fields are installed
    as Custom Fields on frappe Auto Repeat by erpnext.accounts.auto_repeat_extension.custom_fields
  - ERPNextAutoRepeat (this class) overrides the AutoRepeat controller via
    `override_doctype_class` in erpnext/hooks.py
  - `make_new_document` is overridden to dispatch on `repeat_type`:
      * "Reversal" -> ERPNext-side handler (auto_repeat_handler.py)
      * "Copy" or unset -> base copy flow + ERPNext copy-refresh handler
  - Source-validation (skip_if_source_cancelled, follow_amendment_chain,
    current_source_document tracking) lives here too — frappe's upstream
    copy of make_new_document never sees it.

Frappe's auto_repeat.py / .json / .js / test_auto_repeat.py stay at upstream
version-16 byte-for-byte. Easy to keep in sync with upstream.

Refs: badia_docs/signed_off_wp/imp_ga-0001-05+06_upstream_refactor_resume.md
"""

import frappe
from frappe import _
from frappe.automation.doctype.auto_repeat.auto_repeat import AutoRepeat
from frappe.utils import getdate


class ERPNextAutoRepeat(AutoRepeat):
	"""Subclass that adds ERPNext-specific behavior via Custom Fields.

	All Custom Fields are read via `self.get("fieldname")` which works
	whether the field is a real DocField or a Custom Field. Behavior
	degrades gracefully when fields aren't present (e.g. before custom-
	field installation on a fresh site).
	"""

	def validate(self):
		# Run frappe's base validate first
		super().validate()
		# Validate ERPNext-side repeat_type handler registration
		self._validate_erpnext_repeat_type()

	def _validate_erpnext_repeat_type(self):
		"""Reject Reversal mode for doctypes without a registered handler."""
		repeat_type = self.get("repeat_type") or "Copy"
		if repeat_type in (None, "", "Copy"):
			return
		handler_path = self._resolve_repeat_handler(repeat_type)
		if not handler_path:
			frappe.throw(_(
				"No Auto Repeat handler registered for repeat_type={0} on doctype {1}. "
				"Add an entry to `auto_repeat_handlers` in your app's hooks.py."
			).format(repeat_type, self.reference_doctype))

	def set_dates(self):
		# For Reversal mode (Custom Field), schedule = start_date directly
		repeat_type = self.get("repeat_type") or "Copy"
		if repeat_type == "Reversal" and not self.disabled:
			self.next_schedule_date = getdate(self.start_date)
			return
		super().set_dates()

	def make_new_document(self, assignee=None):
		"""Dispatch by repeat_type (Custom Field).

		Adds source-validation (skip_if_source_cancelled / follow_amendment_chain)
		on top of frappe's base get-source-and-copy flow.
		"""
		reference_doc = self._get_authoritative_source()
		if reference_doc is None:
			return self._handle_no_valid_source()

		repeat_type = self.get("repeat_type") or "Copy"
		if repeat_type == "Reversal":
			handler_path = self._resolve_repeat_handler("Reversal")
			if not handler_path:
				frappe.throw(_(
					"No Auto Repeat handler registered for repeat_type=Reversal on doctype {0}."
				).format(self.reference_doctype))
			handler = frappe.get_attr(handler_path)
			return handler(auto_repeat=self, reference_doc=reference_doc, assignee=assignee)

		# Copy path — call frappe's logic but inject refresh handlers BEFORE insert.
		return self._make_copy_document_with_refresh(reference_doc, assignee)

	def _make_copy_document_with_refresh(self, reference_doc, assignee=None):
		"""Reimplements frappe's make_new_document for Copy mode + adds refresh hook.

		Mirrors frappe's body so we don't depend on internal helpers, and
		invokes ERPNext-side refresh handlers between copy and insert.
		"""
		from frappe.desk.form.assign_to import add as assign_to

		new_doc = frappe.copy_doc(reference_doc, ignore_no_copy=False)
		self.update_doc(new_doc, reference_doc)
		new_doc.flags.updater_reference = {
			"doctype": self.doctype,
			"docname": self.name,
			"label": _("via Auto Repeat"),
		}

		# ERPNext-side refresh: prices, FX, taxes, payment terms, etc.
		for handler_path in self._resolve_copy_refresh_handlers():
			handler = frappe.get_attr(handler_path)
			handler(auto_repeat=self, new_doc=new_doc, reference_doc=reference_doc)

		new_doc.insert(ignore_permissions=True)
		if assignee:
			args = {
				"assign_to": assignee,
				"doctype": self.reference_doctype,
				"name": new_doc.name,
				"description": new_doc.get_title(),
			}
			assign_to(args=args)
		if self.submit_on_creation:
			new_doc.submit()
		return new_doc

	# ── Source-validation (Custom Field-driven) ───────────────────────────

	def _get_authoritative_source(self):
		"""Resolve the source document, optionally walking the amendment chain.

		Returns None if the source is cancelled and either
		(a) follow_amendment_chain is off, or
		(b) no non-cancelled amendment exists.
		"""
		reference_doc = frappe.get_doc(self.reference_doctype, self.reference_document)
		if getattr(reference_doc, "docstatus", None) == 2:
			if self.get("follow_amendment_chain"):
				latest = self._find_latest_amendment(reference_doc)
				if latest:
					if self.meta.has_field("current_source_document"):
						self.db_set("current_source_document", latest.name)
					return latest
			return None
		if self.meta.has_field("current_source_document"):
			self.db_set("current_source_document", reference_doc.name)
		return reference_doc

	def _find_latest_amendment(self, cancelled_doc):
		"""Walk amended_from -> amended_from chain to find the latest live amendment."""
		seen = {cancelled_doc.name}
		current = cancelled_doc.name
		while True:
			child = frappe.db.get_value(
				self.reference_doctype, {"amended_from": current, "docstatus": ("!=", 2)}, "name"
			)
			if not child or child in seen:
				# No live amendment, or we've hit a cycle.
				if current != cancelled_doc.name:
					try:
						return frappe.get_doc(self.reference_doctype, current)
					except frappe.DoesNotExistError:
						return None
				return None
			seen.add(child)
			# Walk forward — child may itself have been amended.
			next_child = frappe.db.get_value(
				self.reference_doctype, {"amended_from": child}, "name"
			)
			if not next_child:
				return frappe.get_doc(self.reference_doctype, child)
			current = child

	def _handle_no_valid_source(self):
		"""Source is cancelled with no valid amendment — log + disable AR."""
		if self.get("skip_if_source_cancelled"):
			frappe.log_error(
				title="Auto Repeat Skipped",
				message=(
					f"Auto Repeat {self.name}: source "
					f"{self.reference_doctype} {self.reference_document} is "
					f"cancelled with no valid amendment. Disabling."
				),
			)
			self.db_set("disabled", 1)
			self.db_set("status", "Completed")
			return None
		# No skip flag — fall back to frappe's "doc not found" behavior implicitly.
		frappe.throw(_(
			"Source document {0} {1} is cancelled. Enable 'Skip if Source Cancelled' "
			"or 'Follow Amendment Chain' to handle this gracefully."
		).format(self.reference_doctype, self.reference_document))

	# ── Hook resolution ───────────────────────────────────────────────────

	def _resolve_repeat_handler(self, repeat_type):
		"""Look up `auto_repeat_handlers[doctype][repeat_type]` in app hooks."""
		hooks = frappe.get_hooks("auto_repeat_handlers") or {}
		by_doctype = hooks.get(self.reference_doctype)
		if isinstance(by_doctype, list):
			merged = {}
			for entry in by_doctype:
				if isinstance(entry, dict):
					merged.update(entry)
			by_doctype = merged
		if not isinstance(by_doctype, dict):
			return None
		return by_doctype.get(repeat_type)

	def _resolve_copy_refresh_handlers(self):
		"""Return all matching dotted-paths for Copy-mode refresh handlers."""
		hooks = frappe.get_hooks("auto_repeat_copy_refresh_handlers") or {}
		paths = []
		for key in ("*", self.reference_doctype):
			value = hooks.get(key)
			if value is None:
				continue
			if isinstance(value, str):
				paths.append(value)
			elif isinstance(value, list):
				paths.extend([v for v in value if isinstance(v, str)])
		return paths


@frappe.whitelist()
def create_next_document_now(auto_repeat_name: str) -> dict:
	"""Manually trigger the next document creation for an Auto Repeat.

	Wraps `auto_repeat.make_new_document()` so the form-level "Create
	Document Now" button can fire one tick on demand without waiting for
	the scheduler. Useful for UAT and ops verification.

	Returns a dict with the new doc's doctype + name, or an `error` key
	if creation was skipped (e.g. source cancelled with skip_if_source_cancelled).
	"""
	ar = frappe.get_doc("Auto Repeat", auto_repeat_name)
	# Auto Repeat is not submittable per its doctype JSON; the daily
	# scheduler fires on status=='Active' && !disabled. Mirror that gate
	# here rather than requiring docstatus=1.
	if ar.disabled:
		frappe.throw(_("Auto Repeat is disabled."))
	if (ar.status or "") != "Active":
		frappe.throw(_("Auto Repeat must be Active (current status: {0}).").format(ar.status or "<empty>"))
	new_doc = ar.make_new_document()
	if new_doc is None:
		return {"error": "no_document_created", "message": "make_new_document returned None — check the AR's log for the skip reason."}
	return {"doctype": new_doc.doctype, "name": new_doc.name}
