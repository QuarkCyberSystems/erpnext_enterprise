# Payment Reconciliation Entry

Submittable clearing-document doctype that records each (payment, invoice) reconciliation as a separate, auditable accounting event. Modelled on SAP's Clearing Document.

## When does a PRE get created?

Under `Accounts Settings.enable_immutable_ledger=1`, every allocation produced by the Payment Reconciliation tool — and by the auto-recon job (`Process Payment Reconciliation`) — produces one PRE per (payment, invoice) pair. The PRE owns the clearing GL pair (advance account → invoice receivable/payable) and the corresponding `Advance Payment Ledger Entry` row.

Under `enable_immutable_ledger=0` no PRE is created; reconciles fall through to the legacy `update_reference_in_payment_entry` / `update_reference_in_journal_entry` flow.

## What does the PRE control?

- The clearing GL pair, posted under `voucher_type="Payment Reconciliation Entry"`, `voucher_no=<PRE.name>`, `voucher_detail_no=<PE Reference row name>`. The PE's own original GL (Cash → Advance Account) at PE submit time is preserved unchanged.
- An `Advance Payment Ledger Entry` row with `event="Reconcile"` and `payment_reconciliation_entry=<PRE.name>`.
- A single-column `db_set` write of `reconciliation_entry` on the linked `Payment Entry Reference` row — the only post-submit write on the PE side, and the only place the PE is touched after submission.

## Reversal model

Unreconcile produces a second PRE with `is_reversal=1`, `reversal_of=<original PRE.name>`. The reversal's `on_submit` posts a Dr↔Cr-swapped clearing GL pair at today's date, inserts a negative-amount APLE row, and `db_set`s the original PRE's `is_unreconciled=1` / `unreconciled_by=<reversal>` / `unreconciled_on=<today>`. The original PRE is never cancelled or deleted.

`Unreconcile Payment.on_submit` is the user-facing trigger — it walks its allocations, looks up the matching original PRE, and creates the reversal PRE. Direct `frappe.cancel` on a PRE is blocked under Immutable Ledger.

## Cross-reference

- WP GA-0001-03_Payment_Reconciliation.docx — design specification
- imp_ga-0001-03.md — execution plan
- GA-0001-01 — JE on_cancel reversal pair (related)
- GA-0001-02 — Stock-repost adjustment SLE+GL pair (related)
