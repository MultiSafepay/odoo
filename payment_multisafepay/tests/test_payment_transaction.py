# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
from unittest.mock import patch, MagicMock

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestPaymentTransaction(TransactionCase):
    def setUp(self):
        super().setUp()
        self.provider = self.env["payment.provider"].create(
            {
                "name": "MultiSafepay Test",
                "code": "multisafepay",
                "state": "test",
            }
        )

        self.partner = self.env["res.partner"].create(
            {
                "name": "Test Customer",
                "email": "test@example.com",
            }
        )

        self.currency = (
            self.env["res.currency"]
            .with_context(active_test=False)
            .search(
                [("name", "=", "EUR")],
                limit=1,
            )
        )

        if not self.currency:
            self.currency = self.env["res.currency"].create(
                {
                    "name": "EUR",
                    "symbol": "€",
                    "rate": 1.0,
                }
            )

    def test_compute_reference(self):
        """Test _compute_reference method for MultiSafepay transactions"""

        reference = self.env["payment.transaction"]._compute_reference("multisafepay")

        self.assertIsInstance(reference, str)
        self.assertTrue(reference)
        self.assertNotIn(" ", reference)

    def test_get_multisafepay_status_to_odoo_state(self):
        tx = self.env["payment.transaction"]
        self.assertEqual(tx._get_multisafepay_status_to_odoo_state("completed"), "done")
        self.assertEqual(tx._get_multisafepay_status_to_odoo_state("uncleared"), "pending")
        self.assertEqual(tx._get_multisafepay_status_to_odoo_state("declined"), "cancel")
        self.assertEqual(tx._get_multisafepay_status_to_odoo_state("void"), "cancel")
        self.assertEqual(tx._get_multisafepay_status_to_odoo_state("initialized"), "draft")
        self.assertEqual(tx._get_multisafepay_status_to_odoo_state("unknown_status"), "error")

    def test_process_notification_data(self):
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-1",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
        })
        
        # Test draft/initialized
        tx._process_notification_data({
            "reference": "TEST-REF-1",
            "status": "initialized",
        })
        self.assertEqual(tx.state, "draft")
        
        # Test completed -> done
        tx._process_notification_data({
            "reference": "TEST-REF-1",
            "status": "completed",
        })
        self.assertEqual(tx.state, "done")
        
    @patch("odoo.addons.payment_multisafepay.models.payment_provider.PaymentProvider.get_multisafepay_sdk")
    def test_send_refund_request(self, mock_get_sdk):
        mock_sdk = MagicMock()
        mock_order_manager = MagicMock()
        mock_sdk.get_order_manager.return_value = mock_order_manager
        mock_get_sdk.return_value = mock_sdk
        
        # Mock the order response
        mock_order_response = MagicMock()
        mock_order_data = MagicMock()
        mock_order_data.status = "completed"
        mock_order_data.amount_refunded = 0
        mock_order_response.get_data.return_value = mock_order_data
        mock_order_manager.get.return_value = mock_order_response
        
        # Mock refund response
        mock_refund_response = MagicMock()
        mock_refund_data = MagicMock()
        mock_refund_data.transaction_id = "REFUND-1"
        mock_refund_response.get_data.return_value = mock_refund_data
        mock_order_manager.refund.return_value = mock_refund_response
        
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-2",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
            "state": "done",
            "provider_reference": "MSP-REF-2",
        })
        
        refund_tx = tx._send_refund_request(amount_to_refund=5.0)
        
        self.assertEqual(refund_tx.provider_reference, "REFUND-1")
        mock_order_manager.refund.assert_called_once()

    def test_get_specific_processing_values(self):
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-PROCESS",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
        })
        values = tx._get_specific_processing_values({})
        self.assertEqual(values.get("reference"), "TEST-REF-PROCESS")
        
    def test_get_specific_rendering_values(self):
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-RENDER",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
        })
        values = tx._get_specific_rendering_values({"some_val": 1})
        self.assertEqual(values.get("some_val"), 1)

    def test_get_tx_from_notification_data(self):
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-NOTIFY",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
        })
        found_tx = self.env["payment.transaction"]._get_tx_from_notification_data(
            "multisafepay", {"reference": "TEST-REF-NOTIFY"}
        )
        self.assertEqual(found_tx.id, tx.id)

    @patch("odoo.addons.payment_multisafepay.models.payment_provider.PaymentProvider.get_multisafepay_sdk")
    def test_send_refund_request_already_refunded(self, mock_get_sdk):
        mock_sdk = MagicMock()
        mock_order_manager = MagicMock()
        mock_sdk.get_order_manager.return_value = mock_order_manager
        mock_get_sdk.return_value = mock_sdk
        
        # Mock the order response as already refunded
        mock_order_response = MagicMock()
        mock_order_data = MagicMock()
        mock_order_data.status = "refunded"
        mock_order_response.get_data.return_value = mock_order_data
        mock_order_manager.get.return_value = mock_order_response
        
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-REFUNDED",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
            "state": "done",
            "provider_reference": "MSP-REF-3",
        })
        
        with self.assertRaises(UserError) as cm:
            tx._send_refund_request(amount_to_refund=5.0)
            
        self.assertIn("already been fully refunded", str(cm.exception))

    @patch("odoo.addons.payment_multisafepay.models.payment_provider.PaymentProvider.get_multisafepay_sdk")
    def test_send_refund_request_exceeds_amount(self, mock_get_sdk):
        mock_sdk = MagicMock()
        mock_order_manager = MagicMock()
        mock_sdk.get_order_manager.return_value = mock_order_manager
        mock_get_sdk.return_value = mock_sdk
        
        # Mock the order response as partially refunded
        mock_order_response = MagicMock()
        mock_order_data = MagicMock()
        mock_order_data.status = "completed"
        mock_order_data.amount_refunded = 8.0 # Already refunded 8, remaining 2
        mock_order_response.get_data.return_value = mock_order_data
        mock_order_manager.get.return_value = mock_order_response
        
        tx = self.env["payment.transaction"].create({
            "amount": 10.0,
            "currency_id": self.currency.id,
            "reference": "TEST-REF-EXCEEDS",
            "provider_id": self.provider.id,
            "partner_id": self.partner.id,
            "state": "done",
            "provider_reference": "MSP-REF-4",
        })
        
        with self.assertRaises(UserError) as cm:
            tx._send_refund_request(amount_to_refund=5.0) # 5 > 2
            
        self.assertIn("exceeds available amount", str(cm.exception))
