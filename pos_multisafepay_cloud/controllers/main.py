# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import json
import logging

from odoo import _, http
from odoo.http import request

from ..helpers.frontend_response_builder import (
    _FrontendResponseBuilder,
)
from ..helpers.notification_payload import (
    _NotificationPayload,
)
from ..helpers.notification_validator import (
    _NotificationValidator,
)

_logger = logging.getLogger(__name__)


class PosMultiSafepayCloudController(http.Controller):
    def _find_payment(self, env, reference):
        """Find the corresponding payment record for a given reference."""
        PaymentModel = env["pos.multisafepay.cloud.payment"].sudo()
        return PaymentModel._find_payment(
            order_id=reference,
            msp_cloud_uid=reference,
            include_remote=True,
        )

    @http.route(
        "/pos_multisafepay_cloud/notification",
        type="http",
        methods=["GET"],
        auth="public",
        csrf=False,
    )
    def notification_get(self, **kwargs):
        """Handle MultiSafepay Cloud POS GET status callbacks (Polling)."""
        try:
            # 1. Payload Parsing
            payload = _NotificationPayload.get_from_request(
                "",
                kwargs,
                method="GET",
                json_payload=None,
            )
            notification_payload = payload if isinstance(payload, dict) else {}
            reference = _NotificationPayload.get_reference(notification_payload)

            log_data = {
                "method": "GET",
                "query": _NotificationPayload.sanitize_log_payload(kwargs),
            }

            # 2. Early Validation: Missing Parameter (422)
            if not reference:
                _logger.warning(
                    "MSP Cloud POS notification rejected (No Reference): %s", log_data
                )
                return request.make_response(
                    "Notification rejected: No order reference", status=422
                )

            # 3. Database Lookup (404)
            payment = self._find_payment(request.env, reference)
            if not payment:
                status_code = 404
                status_payload = _FrontendResponseBuilder.error(
                    _(
                        "No MultiSafepay Cloud POS payment was found for this notification."
                    ),
                    status_code=404,
                    extra={"order_id": reference, "notification": notification_payload},
                )
            else:
                # 4. Business Logic: Force Remote Status Check
                status_code = 200
                status_payload = payment._force_remote_status_check(method="GET")

            # 5. Build Log Payload
            log_data.update(
                {
                    "status": status_payload.get("status"),
                    "state": status_payload.get("state"),
                    "order_id": status_payload.get("order_id"),
                    "transaction_id": status_payload.get("transaction_id"),
                    "detail": status_payload.get("detail"),
                    "status_code": status_code,
                }
            )

            # 6. Final HTTP Response Mapping
            if status_code == 200:
                _logger.info("MSP Cloud POS notification processed: %s", log_data)
                return request.make_response("OK", status=200)

            elif status_code == 404:
                _logger.warning("MSP Cloud POS notification rejected: %s", log_data)
                # Mask 404 to prevent information leakage
                return request.make_response("OK", status=404)

        except Exception as e:
            _logger.exception(
                "MSP Cloud POS GET notification failed with unhandled exception: %s", e
            )
            return request.make_response("Internal Server Error", status=500)

    @http.route(
        "/pos_multisafepay_cloud/notification",
        type="http",
        methods=["POST"],
        auth="public",
        csrf=False,
    )
    def notification_webhook(self, **kwargs):
        """Handle MultiSafepay Cloud POS POST webhook payloads."""
        try:
            # 1. JSON Parsing & Syntax Validation (400)
            raw_body = request.httprequest.get_data(as_text=True)
            try:
                json_payload = json.loads(raw_body) if raw_body else {}
            except ValueError:
                _logger.warning(
                    "MSP Cloud POS notification rejected (Malformed JSON): method=POST"
                )
                return request.make_response(
                    "Notification rejected: Malformed JSON", status=400
                )

            # 2. Payload Normalization
            payload = _NotificationPayload.get_from_request(
                raw_body,
                kwargs,
                method="POST",
                json_payload=json_payload,
            )
            notification_payload = payload if isinstance(payload, dict) else {}
            reference = _NotificationPayload.get_reference(
                notification_payload
            ) or _NotificationPayload.get_reference(kwargs)

            log_data = {
                "method": "POST",
                "query": _NotificationPayload.sanitize_log_payload(kwargs),
                "payload": _NotificationPayload.sanitize_log_payload(payload),
            }

            # 3. Early Validation: Missing Parameter (422)
            if not reference:
                _logger.warning(
                    "MSP Cloud POS notification rejected (No Reference): %s", log_data
                )
                return request.make_response(
                    "Notification rejected: No order reference", status=422
                )

            # 4. Database Lookup (404)
            payment = self._find_payment(request.env, reference)
            if not payment:
                status_code = 404
                notification = _FrontendResponseBuilder.error(
                    _(
                        "No MultiSafepay Cloud POS payment was found for this notification."
                    ),
                    status_code=404,
                    extra={"order_id": reference, "notification": notification_payload},
                )
            # 5. Security Validation: HMAC Signature (403)
            elif not _NotificationValidator.validate(
                payment.name,
                payment.payment_method_id,
                raw_body,
                request.httprequest.headers.get("Auth", ""),
            ):
                status_code = 403
                notification = _FrontendResponseBuilder.error(
                    _("The MultiSafepay Cloud POS notification signature is invalid."),
                    status_code=403,
                    extra={"order_id": payment.name},
                )
            # 6. Business Logic: Apply Payload State
            else:
                # Reaching this branch means the payment exists and signature validation did not reject it.
                status_payload = notification_payload
                if not notification_payload.get("status"):
                    remote_status = (
                        payment.payment_method_id._api_get_cloud_order_status(
                            payment.name
                        )
                    )
                    if remote_status and remote_status.get("state") != "failure":
                        status_payload = {**notification_payload, **remote_status}

                payment._apply_notification_payload(status_payload, method="POST")
                status_code = 200
                notification = payment._build_status_payload()

            # 7. Build Log Payload
            log_data.update(
                {
                    "status": notification.get("status"),
                    "state": notification.get("state"),
                    "order_id": notification.get("order_id"),
                    "transaction_id": notification.get("transaction_id"),
                    "detail": notification.get("detail"),
                    "status_code": status_code,
                }
            )

            # 8. Final HTTP Response Mapping
            if status_code == 200:
                _logger.info("MSP Cloud POS notification processed: %s", log_data)
                return request.make_response("OK", status=200)

            elif status_code in (403, 404):
                _logger.warning("MSP Cloud POS notification rejected: %s", log_data)
                # Mask 403 and 404 to prevent information leakage
                return request.make_response("KO", status=status_code)

        except Exception as e:
            _logger.exception(
                "MSP Cloud POS POST notification failed with unhandled exception: %s", e
            )
            return request.make_response("Internal Server Error", status=500)
