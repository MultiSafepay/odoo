import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

SENSITIVE_LOG_KEYS = (
    "token",
    "auth",
    "key",
    "secret",
    "signature",
    "hmac",
    "hash",
    "checksum",
    "password",
)


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
        raw_body = request.httprequest.get_data(as_text=True)
        method = request.httprequest.method
        payload = self._get_notification_payload(raw_body, kwargs, method=method)
        log_payload = self._sanitize_notification_log_payload(payload)
        log_query = self._sanitize_notification_log_payload(kwargs)
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

    def _get_notification_payload(self, raw_body, kwargs, method=None):
        if (method or "").upper() == "GET":
            order_id = kwargs.get("order_id")
            return {"order_id": order_id} if order_id else {}

        payload = request.httprequest.get_json(silent=True) or {}
        if not payload and raw_body:
            try:
                payload = json.loads(raw_body)
            except ValueError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return self._normalize_notification_payload(payload)

    def _normalize_notification_payload(self, payload):
        normalized_payload = dict(payload or {})

        nested_payload = normalized_payload.get("data")
        if isinstance(nested_payload, dict):
            normalized_payload = {
                **nested_payload,
                **{key: value for key, value in normalized_payload.items() if key != "data"},
            }

        for nested_key in ("order", "payment", "transaction"):
            nested_value = normalized_payload.get(nested_key)
            if isinstance(nested_value, dict):
                normalized_payload = {
                    **nested_value,
                    **{
                        key: value
                        for key, value in normalized_payload.items()
                        if key != nested_key
                    },
                }

        return normalized_payload

    def _sanitize_notification_log_payload(self, payload):
        if not isinstance(payload, dict):
            return {}

        sanitized_payload = {}
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if any(
                secret_key in normalized_key
                for secret_key in SENSITIVE_LOG_KEYS
            ):
                sanitized_payload[key] = "***"
            elif isinstance(value, dict):
                sanitized_payload[key] = self._sanitize_notification_log_payload(value)
            else:
                sanitized_payload[key] = value
        return sanitized_payload
