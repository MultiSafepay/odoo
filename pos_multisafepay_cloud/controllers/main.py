# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import json
import logging

from odoo import http
from odoo.http import request

from odoo.addons.pos_multisafepay_cloud.helpers.notification_payload import (
    _NotificationPayload,
)

_logger = logging.getLogger(__name__)


class PosMultiSafepayCloudController(http.Controller):
    @http.route(
        [
            "/pos_multisafepay_cloud/notification",
        ],
        type="http",
        methods=["POST", "GET"],
        auth="public",
        csrf=False,
    )
    def notification(self, **kwargs):
        """Handle MultiSafepay Cloud POS notifications.

        Accepts both GET status callbacks and POST webhook payloads, delegates the
        functional validation to the tracking model and returns an HTTP response for
        MultiSafepay.

        :param kwargs: Query-string or form parameters received by the route.
        :return: HTTP response consumed by MultiSafepay.
        """
        raw_body = request.httprequest.get_data(as_text=True)
        method = request.httprequest.method
        payload = _NotificationPayload.get_from_request(
            raw_body,
            kwargs,
            method=method,
            json_payload=request.httprequest.get_json(silent=True),
        )
        log_payload = _NotificationPayload.sanitize_log_payload(payload)
        log_query = _NotificationPayload.sanitize_log_payload(kwargs)
        notification = (
            request.env["pos.multisafepay.cloud.payment"]
            .sudo()
            .process_notification(
                payload,
                raw_body=raw_body,
                auth_header=request.httprequest.headers.get("Auth", ""),
                method=method,
            )
        )

        if notification.get("status_code"):
            _logger.warning(
                "MSP Cloud POS notification rejected: method=%s query=%s payload=%s status=%s state=%s order_id=%s detail=%s",
                method,
                log_query,
                log_payload,
                notification.get("status"),
                notification.get("state"),
                notification.get("order_id"),
                notification.get("detail"),
            )
            return request.make_response(
                notification.get("detail") or "Notification rejected",
                status=notification.get("status_code") or 400,
            )

        _logger.info(
            "MSP Cloud POS notification processed: method=%s query=%s payload=%s status=%s state=%s order_id=%s transaction_id=%s",
            method,
            log_query,
            log_payload,
            notification.get("status"),
            notification.get("state"),
            notification.get("order_id"),
            notification.get("transaction_id"),
        )
        return request.make_response("OK", status=200)

