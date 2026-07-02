from unittest.mock import MagicMock, patch

from odoo.tests.common import HttpCase, TransactionCase

from ..controllers.main import PosMultiSafepayCloudController


class TestMainController(HttpCase):

    @patch("odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._process_post_notification")
    def test_post_returns_422(self, mock_process):
        """Ensure POST requests emitting 422 are NOT masked."""
        mock_process.return_value = {"status_code": 422}
        
        response = self.url_open(
            "/pos_multisafepay_cloud/notification", 
            data="{}", 
            headers={"Content-Type": "application/json"}
        )
        self.assertEqual(response.status_code, 422)

    @patch("odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._process_post_notification")
    def test_post_masks_404_as_200(self, mock_process):
        """Ensure POST requests emitting 404 ARE masked as 200 OK."""
        mock_process.return_value = {"status_code": 404}
        
        response = self.url_open(
            "/pos_multisafepay_cloud/notification", 
            data="{}", 
            headers={"Content-Type": "application/json"}
        )
        self.assertEqual(response.status_code, 200)

    @patch("odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._process_get_notification")
    def test_get_returns_422(self, mock_process):
        """Ensure GET requests emitting 422 are NOT masked."""
        mock_process.return_value = {"status_code": 422}
        
        response = self.url_open("/pos_multisafepay_cloud/notification")
        self.assertEqual(response.status_code, 422)

    @patch("odoo.addons.pos_multisafepay_cloud.controllers.main.PosMultiSafepayCloudController._process_get_notification")
    def test_get_masks_404_as_200(self, mock_process):
        """Ensure GET requests emitting 404 ARE masked as 200 OK."""
        mock_process.return_value = {"status_code": 404}
        
        response = self.url_open("/pos_multisafepay_cloud/notification")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "OK")


class TestPosMultiSafepayCloudControllerMethods(TransactionCase):

    def setUp(self):
        super().setUp()
        self.controller = PosMultiSafepayCloudController()
        self.payload_no_ref = {}
        self.payload_with_ref = {"transactionid": "12345"}
        
        # Mock Odoo environment
        self.mock_env = MagicMock()
        self.mock_payment_model = MagicMock()
        self.mock_env.__getitem__.return_value.sudo.return_value = self.mock_payment_model
        
        self.mock_payment = MagicMock()
        self.mock_payment.name = "12345"
        self.mock_payment_method = MagicMock()
        self.mock_payment.payment_method_id = self.mock_payment_method

    def test_missing_reference_returns_422(self):
        response = self.controller._process_post_notification(
            self.mock_env,
            self.payload_no_ref,
        )
        self.assertEqual(response.get("status_code"), 422)

    def test_payment_not_found_returns_404(self):
        self.mock_payment_model._find_payment.return_value = None
        
        response = self.controller._process_post_notification(
            self.mock_env,
            self.payload_with_ref,
        )
        self.assertEqual(response.get("status_code"), 404)

    @patch("odoo.addons.pos_multisafepay_cloud.controllers.main._NotificationValidator.validate")
    def test_invalid_signature_returns_403(self, mock_validate):
        self.mock_payment_model._find_payment.return_value = self.mock_payment
        mock_validate.return_value = False
        
        response = self.controller._process_post_notification(
            self.mock_env,
            self.payload_with_ref,
        )
        self.assertEqual(response.get("status_code"), 403)

    @patch("odoo.addons.pos_multisafepay_cloud.controllers.main._NotificationValidator.validate")
    def test_valid_payload_calls_apply(self, mock_validate):
        self.mock_payment_model._find_payment.return_value = self.mock_payment
        mock_validate.return_value = True
        
        self.mock_payment._build_status_payload.return_value = {"status_code": 200, "result": "success"}
        
        response = self.controller._process_post_notification(
            self.mock_env,
            self.payload_with_ref,
        )
        self.assertEqual(response.get("status_code"), 200)
        self.mock_payment._apply_notification_payload.assert_called_once_with(self.payload_with_ref, method="POST")

    def test_get_calls_force_remote_status(self):
        self.mock_payment_model._find_payment.return_value = self.mock_payment
        self.mock_payment._force_remote_status_check.return_value = {"status_code": 200, "result": "success"}

        response = self.controller._process_get_notification(
            self.mock_env,
            self.payload_with_ref,
        )
        self.assertEqual(response.get("status_code"), 200)
        self.mock_payment._force_remote_status_check.assert_called_once_with(method="GET")
