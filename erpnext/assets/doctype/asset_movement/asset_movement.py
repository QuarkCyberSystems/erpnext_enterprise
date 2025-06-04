# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_link_to_form

from erpnext.assets.doctype.asset_activity.asset_activity import add_asset_activity


class AssetMovement(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.assets.doctype.asset_movement_item.asset_movement_item import AssetMovementItem

		amended_from: DF.Link | None
		assets: DF.Table[AssetMovementItem]
		company: DF.Link
		purpose: DF.Literal["", "Issue", "Receipt", "Transfer", "Transfer and Issue"]
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		transaction_date: DF.Datetime
	# end: auto-generated types

	def validate(self):
		for d in self.assets:
			self.validate_asset(d)
			self.validate_movement(d)

	def validate_asset(self, d):
		status, company = frappe.db.get_value("Asset", d.asset, ["status", "company"])
		if self.purpose == "Transfer" and status in ("Draft", "Scrapped", "Sold"):
			frappe.throw(_("{0} asset cannot be transferred").format(status))

		if company != self.company:
			frappe.throw(_("Asset {0} does not belong to company {1}").format(d.asset, self.company))

	def validate_movement(self, d):
		if self.purpose == "Transfer and Issue":
			self.validate_location_and_employee(d)
		elif self.purpose in ["Receipt", "Transfer"]:
			self.validate_location(d)
		else:
			self.validate_employee(d)

	def validate_location_and_employee(self, d):
		self.validate_location(d)
		self.validate_employee(d)

	def validate_location(self, d):
		if self.purpose in ["Transfer", "Transfer and Issue"]:
			current_location = frappe.db.get_value("Asset", d.asset, "location")
			if d.source_location:
				if current_location != d.source_location:
					frappe.throw(
						_("Asset {0} does not belongs to the location {1}").format(d.asset, d.source_location)
					)
			else:
				d.source_location = current_location

			if not d.target_location:
				frappe.throw(_("Target Location is required for transferring Asset {0}").format(d.asset))
			if d.source_location == d.target_location:
				frappe.throw(_("Source and Target Location cannot be same"))

		if self.purpose == "Receipt":
			if not d.target_location:
				frappe.throw(_("Target Location is required while receiving Asset {0}").format(d.asset))
			if d.to_employee and frappe.db.get_value("Employee", d.to_employee, "company") != self.company:
				frappe.throw(
					_("Employee {0} does not belongs to the company {1}").format(d.to_employee, self.company)
				)

	def validate_employee(self, d):
		if self.purpose == "Tranfer and Issue":
			if not d.from_employee:
				frappe.throw(_("From Employee is required while issuing Asset {0}").format(d.asset))

		if d.from_employee:
			current_custodian = frappe.db.get_value("Asset", d.asset, "custodian")

			if current_custodian != d.from_employee:
				frappe.throw(
					_("Asset {0} does not belongs to the custodian {1}").format(d.asset, d.from_employee)
				)

		if not d.to_employee:
			frappe.throw(_("Employee is required while issuing Asset {0}").format(d.asset))

		if d.to_employee and frappe.db.get_value("Employee", d.to_employee, "company") != self.company:
			frappe.throw(
				_("Employee {0} does not belongs to the company {1}").format(d.to_employee, self.company)
			)

	def on_submit(self):
		self.set_latest_location_and_custodian_in_asset()

	def on_cancel(self):
		self.set_latest_location_and_custodian_in_asset()

	def set_latest_location_and_custodian_in_asset(self):
		current_location, current_employee = "", ""
		cond = "1=1"

		for d in self.assets:
			args = {"asset": d.asset, "company": self.company}

			# latest entry corresponds to current document's location, employee when transaction date > previous dates
			# In case of cancellation it corresponds to previous latest document's location, employee
			latest_movement_entry = frappe.db.sql(
				f"""
				SELECT asm_item.target_location, asm_item.to_employee
				FROM `tabAsset Movement Item` asm_item, `tabAsset Movement` asm
				WHERE
					asm_item.parent=asm.name and
					asm_item.asset=%(asset)s and
					asm.company=%(company)s and
					asm.docstatus=1 and {cond}
				ORDER BY
					asm.transaction_date desc limit 1
				""",
				args,
			)

			if latest_movement_entry:
				current_location = latest_movement_entry[0][0]
				current_employee = latest_movement_entry[0][1]

			frappe.db.set_value("Asset", d.asset, "location", current_location, update_modified=False)
			frappe.db.set_value("Asset", d.asset, "custodian", current_employee, update_modified=False)

			if current_location and current_employee:
				add_asset_activity(
					d.asset,
					_("Asset received at Location {0} and issued to Employee {1}").format(
						get_link_to_form("Location", current_location),
						get_link_to_form("Employee", current_employee),
					),
				)
			elif current_location:
				add_asset_activity(
					d.asset,
					_("Asset transferred to Location {0}").format(
						get_link_to_form("Location", current_location)
					),
				)
			elif current_employee:
				add_asset_activity(
					d.asset,
					_("Asset issued to Employee {0}").format(get_link_to_form("Employee", current_employee)),
				)
