# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from unittest.mock import MagicMock, patch

from odoo.tests.common import HttpCase


class TestMainController(HttpCase):
    def test_post_without_reference_returns_422(self):
        response = self.url_open(
            "/pos_multisafepay_cloud/notification",
            data="{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 422)

    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._find_payment"
    )
    def test_post_masks_missing_payment_as_200(self, mock_find_payment):
        mock_find_payment.return_value = None

        response = self.url_open(
            "/pos_multisafepay_cloud/notification",
            data='{"transactionid": "12345"}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")

    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main._NotificationValidator.validate"
    )
    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._find_payment"
    )
    def test_post_masks_invalid_signature_as_200(
        self, mock_find_payment, mock_validate
    ):
        payment = MagicMock()
        payment.name = "12345"
        mock_find_payment.return_value = payment
        mock_validate.return_value = False

        response = self.url_open(
            "/pos_multisafepay_cloud/notification",
            data='{"transactionid": "12345", "status": "completed"}',
            headers={"Content-Type": "application/json", "Auth": "invalid"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")

    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main._NotificationValidator.validate"
    )
    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._find_payment"
    )
    def test_post_valid_payload_applies_notification(
        self, mock_find_payment, mock_validate
    ):
        payment = MagicMock()
        payment.name = "12345"
        payment._build_status_payload.return_value = {"status_code": 200}
        mock_find_payment.return_value = payment
        mock_validate.return_value = True

        response = self.url_open(
            "/pos_multisafepay_cloud/notification",
            data='{"transactionid": "12345", "status": "completed"}',
            headers={"Content-Type": "application/json", "Auth": "valid"},
        )
        self.assertEqual(response.status_code, 200)
        payment._apply_notification_payload.assert_called_once_with(
            {"transactionid": "12345", "status": "completed"}, method="POST"
        )

    def test_get_without_reference_returns_422(self):
        response = self.url_open("/pos_multisafepay_cloud/notification")
        self.assertEqual(response.status_code, 422)

    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._find_payment"
    )
    def test_get_masks_missing_payment_as_200(self, mock_find_payment):
        mock_find_payment.return_value = None

        response = self.url_open(
            "/pos_multisafepay_cloud/notification?transactionid=12345"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")

    @patch(
        "odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._find_payment"
    )
    def test_get_calls_force_remote_status(self, mock_find_payment):
        payment = MagicMock()
        payment._force_remote_status_check.return_value = {"status_code": 200}
        mock_find_payment.return_value = payment

        response = self.url_open(
            "/pos_multisafepay_cloud/notification?transactionid=12345"
        )
        self.assertEqual(response.status_code, 200)
        payment._force_remote_status_check.assert_called_once_with(method="GET")
