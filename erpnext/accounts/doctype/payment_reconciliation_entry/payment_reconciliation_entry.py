# Copyright (c) 2026, QuarkCyberSystems and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentReconciliationEntry(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		account: DF.Link
		allocated_amount: DF.Currency
		amended_from: DF.Link | None
		base_allocated_amount: DF.Currency
		company: DF.Link
		cost_center: DF.Link | None
		currency: DF.Link | None
		exchange_gain_loss: DF.Currency
		exchange_gain_loss_journal: DF.Link | None
		exchange_rate: DF.Float
		finance_book: DF.Link | None
		invoice_name: DF.DynamicLink
		invoice_type: DF.Link
		is_reversal: DF.Check
		is_unreconciled: DF.Check
		party: DF.DynamicLink
		party_type: DF.Link
		payment_name: DF.DynamicLink
		payment_reference_row: DF.Data | None
		payment_type: DF.Link
		process_payment_reconciliation_log: DF.Link | None
		project: DF.Link | None
		reconciliation_date: DF.Date
		reversal_of: DF.Link | None
		unreconciled_by: DF.Link | None
		unreconciled_on: DF.Date | None
	# end: auto-generated types

	pass
