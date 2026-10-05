# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged

from ..utils import _get_default_payment_method_image

PAYMENT_URL = "https://pay.example.test/checkout"
API_KEY = "test-api-key"


@tagged("post_install", "-at_install")
class TestMultiSafepayControllers(HttpCase):
    # migracion_19_20: ir.config_parameter.get_param and the t-esc QWeb directive are gone
    # in Odoo 20; these tests drive the redirect route and the status page over HTTP.

    def setUp(self):
        super().setUp()
        # Public session bound to the test database; url_open has none by default.
        self.authenticate(None, None)
        self.provider = self.env["payment.provider"].create(
            {
                "name": "MultiSafepay Controller Test",
                "code": "multisafepay",
                "multisafepay_api_key": API_KEY,
            }
        )
        self.method = self.env["payment.method"].create(
            {
                "name": "iDEAL",
                "code": "multisafepay_ideal",
                "provider_id": self.provider.id,
                "image": _get_default_payment_method_image(),
            }
        )
        self.partner = self.env["res.partner"].create(
            {
                "name": "Buyer Example",
                "email": "buyer@example.com",
                "phone": "+31612345678",
                "street": "Main Street 1",
                "zip": "1011AA",
                "city": "Amsterdam",
                "country_id": self.env.ref("base.nl").id,
            }
        )
        self.tx = self.env["payment.transaction"].create(
            {
                "provider_id": self.provider.id,
                "payment_method_id": self.method.id,
                "reference": "TEST-MSP-HTTP-001",
                "amount": 10.0,
                "currency_id": self.env.ref("base.EUR").id,
                "partner_id": self.partner.id,
                "operation": "online_redirect",
            }
        )
        self.order_requests = []

    def _fake_sdk(self, error=None):
        def create(order_request):
            self.order_requests.append(order_request)
            if error:
                raise error
            order = SimpleNamespace(
                order_id=order_request.order_id, payment_url=PAYMENT_URL
            )
            return SimpleNamespace(get_data=lambda: order, get_raw=lambda: {})

        manager = SimpleNamespace(create=create)
        return SimpleNamespace(get_order_manager=lambda: manager)

    def _fake_sdk_with_order(
        self, status, transaction_id="987654", related_transactions=()
    ):
        order = SimpleNamespace(
            status=status,
            transaction_id=transaction_id,
            related_transactions=list(related_transactions),
        )
        manager = SimpleNamespace(
            get=lambda reference: SimpleNamespace(get_data=lambda: order)
        )
        return SimpleNamespace(get_order_manager=lambda: manager)

    def _open_with_sdk(self, sdk, url, **kwargs):
        with patch.object(
            type(self.provider), "get_multisafepay_sdk", lambda provider: sdk
        ):
            return self.url_open(url, **kwargs)

    def _post_redirect(self, sdk, **kwargs):
        return self._open_with_sdk(
            sdk,
            "/payment/multisafepay/redirect",
            data={"reference": self.tx.reference},
            **kwargs,
        )

    def test_redirect_sends_the_customer_to_the_payment_page(self):
        response = self._post_redirect(self._fake_sdk(), allow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], PAYMENT_URL)
        order_request = self.order_requests[0]
        self.assertEqual(order_request.order_id, self.tx.reference)
        self.assertEqual(order_request.currency, "EUR")
        self.assertEqual(order_request.amount, 1000)

    def test_callbacks_use_the_configured_base_url(self):
        self.env["ir.config_parameter"].sudo().set_str(
            "web.base.url", "https://shop.example.com"
        )

        self._post_redirect(self._fake_sdk(), allow_redirects=False)

        payment_options = self.order_requests[0].payment_options
        self.assertTrue(
            payment_options.notification_url.startswith("https://shop.example.com/")
        )

    def test_redirect_error_message_is_shown_on_the_status_page(self):
        sdk = self._fake_sdk(error=ValidationError("Custom failure message"))

        response = self._post_redirect(sdk)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Payment Error", response.text)
        self.assertIn("Custom failure message", response.text)

    def test_status_page_shows_the_payment_details(self):
        response = self.url_open(
            "/payment/status?payment_method=multisafepay_ideal"
            "&payment_status=completed&amount=10.00&currency=EUR&transaction_id=123"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("MULTISAFEPAY_IDEAL", response.text)
        self.assertIn("completed", response.text)

    def test_webhook_records_the_order_status_and_processing_completes_it(self):
        sdk = self._fake_sdk_with_order("completed")

        response = self._open_with_sdk(
            sdk, f"/payment/multisafepay/webhook?transactionid={self.tx.reference}"
        )

        self.assertEqual(response.status_code, 200)
        queued = self.env["payment.data"].search([("transaction_id", "=", self.tx.id)])
        self.assertEqual(queued.payload, {"status": "completed", "reference": "987654"})

        self.env["payment.transaction"]._run_processing()

        self.assertEqual(self.tx.state, "done")
        self.assertEqual(self.tx.provider_reference, "987654")

    def test_cancel_route_cancels_the_transaction(self):
        response = self.url_open(
            f"/payment/multisafepay/cancel?transactionid={self.tx.reference}",
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("/payment/status?cancelled=1", response.headers["Location"])
        self.env["payment.transaction"]._run_processing()
        self.assertEqual(self.tx.state, "cancel")

    # --- Refunds reported by MultiSafepay ---

    def _refund_entry(self, refund_id="1791205096102997", amount=1000):
        # Shape of the related transaction MultiSafepay sends for a refund.
        return {
            "amount": amount,
            "costs": [],
            "currency": "EUR",
            "description": f"Refund for Odoo order {self.tx.reference}",
            "order_status": "completed",
            "reference_transaction_id": 1791204994102953,
            "refund_order_id": self.tx.reference,
            "status": "completed",
            "transaction_id": int(refund_id),
            "type": "refund",
        }

    def _post_order_webhook(self, status, *related_transactions, api_key=API_KEY):
        payload = {
            "amount": 1000,
            "amount_refunded": sum(r["amount"] for r in related_transactions),
            "currency": "EUR",
            "financial_status": "completed",
            "order_id": self.tx.reference,
            "related_transactions": list(related_transactions),
            "status": status,
            "transaction_id": 1791204994102953,
        }
        body = json.dumps(payload)
        # MultiSafepay signs "<timestamp>:<compact json>" with the API key (HMAC SHA-512).
        compact = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = str(int(time.time()))
        signature = hmac.new(
            api_key.encode(), f"{timestamp}:{compact}".encode(), hashlib.sha512
        ).hexdigest()
        auth = base64.b64encode(f"{timestamp}:{signature}".encode()).decode()
        return self.url_open(
            "/payment/multisafepay/webhook",
            data=body,
            headers={"Auth": auth, "Content-Type": "application/json"},
        )

    def _refunds(self):
        return self.tx.child_transaction_ids.filtered(
            lambda tx: tx.operation == "refund"
        )

    def test_post_webhook_creates_the_refund_made_in_the_multisafepay_panel(self):
        self.tx.with_context(payment_safe_write=True)._set_done()

        response = self._post_order_webhook("refunded", self._refund_entry())

        self.assertEqual(response.status_code, 200)
        refund_tx = self._refunds()
        self.assertEqual(len(refund_tx), 1)
        self.assertEqual(refund_tx.amount, -10.0)
        self.assertEqual(refund_tx.provider_reference, "1791205096102997")

        self.env["payment.transaction"]._run_processing()

        self.assertEqual(refund_tx.state, "done")
        self.assertEqual(self.tx.state, "done")

    def test_post_webhook_sent_twice_creates_a_single_refund(self):
        self.tx.with_context(payment_safe_write=True)._set_done()

        for _attempt in range(2):
            response = self._post_order_webhook("refunded", self._refund_entry())
            self.assertEqual(response.status_code, 200)

        self.assertEqual(len(self._refunds()), 1)
        self.env["payment.transaction"]._run_processing()
        response = self._post_order_webhook("refunded", self._refund_entry())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self._refunds()), 1)

    def test_post_webhook_creates_each_partial_refund(self):
        self.tx.with_context(payment_safe_write=True)._set_done()

        self._post_order_webhook("partial_refunded", self._refund_entry("701", 400))
        self._post_order_webhook(
            "partial_refunded",
            self._refund_entry("701", 400),
            self._refund_entry("702", 250),
        )

        self.assertEqual(sorted(self._refunds().mapped("amount")), [-4.0, -2.5])
        self.assertEqual(
            sorted(self._refunds().mapped("provider_reference")), ["701", "702"]
        )

    def test_post_webhook_with_a_wrong_signature_creates_no_refund(self):
        self.tx.with_context(payment_safe_write=True)._set_done()

        response = self._post_order_webhook(
            "refunded", self._refund_entry(), api_key="another-api-key"
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self._refunds())

    def test_get_webhook_creates_the_refund_made_in_the_multisafepay_panel(self):
        self.tx.with_context(payment_safe_write=True)._set_done()
        related = [
            SimpleNamespace(
                type="refund", status="completed", transaction_id="701", amount=400
            )
        ]
        sdk = self._fake_sdk_with_order(
            "partial_refunded", related_transactions=related
        )

        response = self._open_with_sdk(
            sdk, f"/payment/multisafepay/webhook?transactionid={self.tx.reference}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._refunds().mapped("amount"), [-4.0])
        self.assertEqual(self._refunds().provider_reference, "701")
