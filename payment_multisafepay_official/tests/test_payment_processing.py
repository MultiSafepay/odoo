# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.exceptions import LockError, UserError
from odoo.tests.common import TransactionCase

from ..utils import _get_default_payment_method_image


class TestMultiSafepayPaymentProcessing(TransactionCase):
    # migracion_19_20: Odoo 20 blocks direct writes on transactions and processes recorded
    # payment data asynchronously (_record -> _process -> _apply_updates); these tests cover it.

    def setUp(self):
        super().setUp()
        self.provider = self.env["payment.provider"].create(
            {"name": "MultiSafepay Processing Test", "code": "multisafepay"}
        )
        self.method = self.env["payment.method"].create(
            {
                "name": "iDEAL",
                "code": "multisafepay_ideal",
                "provider_id": self.provider.id,
                "image": _get_default_payment_method_image(),
            }
        )
        self.tx = self.env["payment.transaction"].create(
            {
                "provider_id": self.provider.id,
                "payment_method_id": self.method.id,
                "reference": "TEST-MSP-001",
                "amount": 10.0,
                "currency_id": self.env.ref("base.EUR").id,
                "partner_id": self.env["res.partner"].create({"name": "Buyer"}).id,
                "operation": "online_redirect",
            }
        )

    def _process(self, tx, payment_data):
        tx.with_context(payment_safe_write=True)._process(payment_data)

    def test_direct_writes_are_blocked(self):
        with self.assertRaises(UserError):
            self.tx.write({"provider_reference": "direct"})

    def test_record_queues_the_payment_data(self):
        self.tx._record({"status": "completed", "reference": "MSP-1"})

        queued = self.env["payment.data"].search([("transaction_id", "=", self.tx.id)])
        self.assertEqual(queued.payload, {"status": "completed", "reference": "MSP-1"})

    def test_completed_status_sets_the_transaction_done(self):
        self._process(self.tx, {"status": "completed", "reference": "MSP-1"})

        self.assertEqual(self.tx.state, "done")
        self.assertEqual(self.tx.provider_reference, "MSP-1")

    def test_pending_cancelled_and_declined_statuses(self):
        for status, expected_state in (
            ("pending", "pending"),
            ("cancelled", "cancel"),
            ("declined", "error"),
        ):
            with self.subTest(status=status):
                tx = self.tx.copy({"reference": f"TEST-MSP-{status}"})
                self._process(tx, {"status": status})
                self.assertEqual(tx.state, expected_state)

    def _refund_sdk(self, refund_id="555", refund=None):
        manager = SimpleNamespace(
            get=lambda reference: SimpleNamespace(
                get_data=lambda: SimpleNamespace(
                    status="completed", amount_refunded=None
                )
            ),
            refund=refund
            or (
                lambda reference, payload: SimpleNamespace(
                    # transaction_id is the paid order's transaction, refund_id the refund's own.
                    get_data=lambda: SimpleNamespace(
                        transaction_id=111, refund_id=refund_id
                    ),
                    body={},
                )
            ),
        )
        return SimpleNamespace(get_order_manager=lambda: manager)

    def _request_refund(self, amount=4.0, **sdk_kwargs):
        self.tx.with_context(payment_safe_write=True)._set_done()
        with patch.object(
            type(self.provider),
            "get_multisafepay_sdk",
            return_value=self._refund_sdk(**sdk_kwargs),
        ):
            return self.tx.with_context(payment_safe_write=True)._refund(amount)

    def _queued(self, tx):
        return self.env["payment.data"].search([("transaction_id", "=", tx.id)])

    def test_refund_request_is_queued_and_processed(self):
        refund_tx = self._request_refund(4.0)

        self.assertEqual(refund_tx.operation, "refund")
        self.assertEqual(refund_tx.state, "draft")
        queued = self._queued(refund_tx)
        self.assertEqual(queued.payload["reference"], "555")

        self._process(refund_tx, queued.payload)

        self.assertEqual(refund_tx.state, "done")
        self.assertEqual(refund_tx.provider_reference, "555")

    def test_refund_reference_is_the_refund_id_and_is_set_before_processing(self):
        refund_tx = self._request_refund(4.0)

        # The reference is on the refund even if the queued data is never processed (cron
        # disabled) and the refund is confirmed manually, which skips _apply_updates.
        self.assertEqual(refund_tx.provider_reference, "555")
        self.assertNotEqual(refund_tx.provider_reference, "111")

    def test_refund_without_a_refund_id_does_not_store_the_order_transaction_id(self):
        refund_tx = self._request_refund(4.0, refund_id=None)

        self.assertFalse(refund_tx.provider_reference)
        self.assertNotIn("reference", self._queued(refund_tx).payload)

    def test_refund_request_fails_without_calling_multisafepay_if_source_is_locked(
        self,
    ):
        self.tx.with_context(payment_safe_write=True)._set_done()
        refund = Mock()
        sdk = self._refund_sdk(refund=refund)

        with (
            patch.object(type(self.provider), "get_multisafepay_sdk", return_value=sdk),
            patch.object(type(self.tx), "lock_for_update", side_effect=LockError("x")),
            self.assertRaisesRegex(UserError, "being processed"),
        ):
            self.tx.with_context(payment_safe_write=True)._refund(4.0)

        refund.assert_not_called()

    # --- Refunds reported by the MultiSafepay webhook ---

    def _refund_entry(self, refund_id, amount, status="completed", type_="refund"):
        return SimpleNamespace(
            type=type_, status=status, transaction_id=refund_id, amount=amount
        )

    def _order(self, *entries):
        return SimpleNamespace(related_transactions=list(entries))

    def _sync(self, *entries):
        self.tx.with_context(payment_safe_write=True)._set_done()
        return self.tx._multisafepay_sync_refunds(self._order(*entries))

    def _refunds(self):
        return self.tx.child_transaction_ids.filtered(
            lambda tx: tx.operation == "refund"
        )

    def test_sync_creates_the_refund_requested_in_the_multisafepay_panel(self):
        # Order of the real webhook: refund 777 of EUR 4.00 (amounts are in cents).
        created = self._sync(self._refund_entry("777", 400))

        refund_tx = self._refunds()
        self.assertEqual(created, refund_tx)
        self.assertEqual(refund_tx.amount, -4.0)
        self.assertEqual(refund_tx.provider_reference, "777")
        self.assertEqual(refund_tx.state, "draft")
        queued = self._queued(refund_tx)
        self.assertEqual(
            queued.payload,
            {
                "status": "completed",
                "reference": "777",
                "amount": 4.0,
                "currency": "EUR",
            },
        )

        self._process(refund_tx, queued.payload)

        self.assertEqual(refund_tx.state, "done")

    def test_sync_is_idempotent(self):
        entry = self._refund_entry("777", 400)
        self._sync(entry)
        refund_tx = self._refunds()

        # The same notification arrives again (MultiSafepay sends it more than once).
        self.assertFalse(self.tx._multisafepay_sync_refunds(self._order(entry)))
        self.assertEqual(self._refunds(), refund_tx)
        self.assertEqual(len(self._queued(refund_tx)), 1)

        # And again after the queued data was processed.
        self._process(refund_tx, self._queued(refund_tx).payload)
        self._queued(refund_tx).unlink()
        self.assertFalse(self.tx._multisafepay_sync_refunds(self._order(entry)))
        self.assertEqual(self._refunds(), refund_tx)
        self.assertFalse(self._queued(refund_tx))

    def test_sync_does_not_duplicate_the_refund_requested_from_odoo(self):
        refund_tx = self._request_refund(4.0)

        synced = self.tx._multisafepay_sync_refunds(
            self._order(self._refund_entry("555", 400))
        )

        self.assertFalse(synced)
        self.assertEqual(self._refunds(), refund_tx)
        self.assertEqual(len(self._queued(refund_tx)), 1)

    def test_sync_adopts_a_refund_that_has_no_refund_id(self):
        self.tx.with_context(payment_safe_write=True)._set_done()
        refund_tx = self.tx._create_child_transaction(4.0, is_refund=True)

        synced = self.tx._multisafepay_sync_refunds(
            self._order(self._refund_entry("777", 400))
        )

        self.assertEqual(synced, refund_tx)
        self.assertEqual(self._refunds(), refund_tx)
        self.assertEqual(refund_tx.provider_reference, "777")
        self.assertEqual(self._queued(refund_tx).payload["status"], "completed")

    def test_sync_adopts_a_done_refund_without_reference_and_sets_it(self):
        # Refund confirmed manually before the reference was stored: nothing to record,
        # only the reference is completed.
        self.tx.with_context(payment_safe_write=True)._set_done()
        refund_tx = self.tx._create_child_transaction(4.0, is_refund=True)
        refund_tx.with_context(payment_safe_write=True)._set_done()

        self.tx._multisafepay_sync_refunds(self._order(self._refund_entry("777", 400)))

        self.assertEqual(self._refunds(), refund_tx)
        self.assertEqual(refund_tx.provider_reference, "777")
        self.assertFalse(self._queued(refund_tx))

    def test_sync_adopts_a_refund_created_with_the_order_transaction_id(self):
        # Earlier versions stored the paid order's transaction id on the refund.
        self.tx.with_context(payment_safe_write=True).provider_reference = "ORDER-1"
        self.tx.with_context(payment_safe_write=True)._set_done()
        refund_tx = self.tx._create_child_transaction(
            4.0, is_refund=True, provider_reference="ORDER-1"
        )
        refund_tx.with_context(payment_safe_write=True)._set_done()

        synced = self.tx._multisafepay_sync_refunds(
            self._order(self._refund_entry("777", 400))
        )

        self.assertFalse(synced)
        self.assertEqual(self._refunds(), refund_tx)
        self.assertFalse(self._queued(refund_tx))

    def test_sync_handles_each_partial_refund_separately(self):
        refund_tx = self._request_refund(4.0)  # Refund 555 requested from Odoo.

        synced = self.tx._multisafepay_sync_refunds(
            self._order(
                self._refund_entry("555", 400),
                self._refund_entry("701", 600),
                self._refund_entry("702", 250),
            )
        )

        self.assertEqual(len(self._refunds()), 3)
        self.assertNotIn(refund_tx, synced)
        self.assertEqual(sorted(self._refunds().mapped("amount")), [-6.0, -4.0, -2.5])
        self.assertEqual(
            sorted(self._refunds().mapped("provider_reference")), ["555", "701", "702"]
        )

    def test_sync_ignores_failed_refunds_and_other_transaction_types(self):
        self._sync(
            self._refund_entry("801", 400, status="declined"),
            self._refund_entry("802", 400, type_="payment"),
            self._refund_entry("803", 0),
            self._refund_entry("804", 400, status=None),
        )

        self.assertFalse(self._refunds())

    def test_sync_updates_a_known_refund_when_its_status_changes(self):
        refund_tx = self.tx._create_child_transaction(
            4.0, is_refund=True, provider_reference="777"
        )

        self._sync(self._refund_entry("777", 400, status="declined"))

        self.assertEqual(self._refunds(), refund_tx)
        self.assertEqual(self._queued(refund_tx).payload["status"], "declined")

    def test_sync_skips_refunds_while_the_source_transaction_is_locked(self):
        with patch.object(
            type(self.tx),
            "try_lock_for_update",
            return_value=self.env["payment.transaction"],
        ):
            synced = self._sync(self._refund_entry("777", 400))

        self.assertFalse(synced)
        self.assertFalse(self._refunds())
