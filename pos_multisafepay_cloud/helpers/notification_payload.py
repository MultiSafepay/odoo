# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import json
import logging
from decimal import Decimal

from odoo import _

from ..helpers.utils import (
    _Utils,
)

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


class _NotificationPayload:
    """Parse information and tips from notification and response payloads.

    This class handles the parsing, normalization, and sanitization of raw webhook and API
    payloads received from the Cloud POS terminal. It encapsulates data extraction logic,
    ensuring that the main payment process only deals with structured, safe data, adhering
    to the Single Responsibility Principle.
    """

    @classmethod
    def get_from_request(cls, raw_body, kwargs, method=None, json_payload=None):
        """Extract the notification payload from the HTTP request.

        :param str raw_body: Raw request body received by the controller.
        :param dict kwargs: Query-string or form parameters received by the route.
        :param str method: HTTP method used by the notification request.
        :param dict json_payload: Parsed JSON payload from the request framework.
        :return: Normalized notification payload.
        :rtype: dict
        """
        if (method or "").upper() == "GET":
            return {
                k: kwargs.get(k) for k in ("transactionid", "timestamp") if k in kwargs
            }

        payload = json_payload or {}
        if not payload and raw_body:
            try:
                payload = json.loads(raw_body)
            except ValueError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return cls.normalize(payload)

    @staticmethod
    def normalize(payload):
        """Flatten known nested notification payload shapes."""
        result = dict(payload or {})
        for key in ("data", "order", "payment", "transaction"):
            if isinstance(result.get(key), dict):
                nested = result.pop(key)
                result = nested | result
        return result

    @classmethod
    def sanitize_log_payload(cls, payload):
        """Mask sensitive notification fields before logging."""
        if not isinstance(payload, dict):
            return {}

        sanitized_payload = {}
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if any(secret_key in normalized_key for secret_key in SENSITIVE_LOG_KEYS):
                sanitized_payload[key] = "***"
            elif isinstance(value, dict):
                sanitized_payload[key] = cls.sanitize_log_payload(value)
            elif isinstance(value, list):
                sanitized_payload[key] = [
                    cls.sanitize_log_payload(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized_payload[key] = value
        return sanitized_payload

    @staticmethod
    def get_reference(payload):
        """Extract the best order reference match from a notification.

        :param dict payload: The notification webhook payload or query parameters.
        :return: A string reference or empty string.
        :rtype: str
        """
        for key in ("transactionid", "order_id"):
            reference = payload.get(key)
            if reference:
                return str(reference)
        return ""

    @classmethod
    def get_remote_tip_amount(cls, payload):
        """Sum the tip amounts declared in a notification payload.

        :param dict payload: The notification payload.
        :return: Total remote tip amount in cents.
        :rtype: int
        """
        amount_details_tip = cls.get_amount_details_tip_amount(payload)
        if amount_details_tip:
            return int(amount_details_tip)

        total = Decimal("0")
        costs = payload.get("costs") if isinstance(payload, dict) else None
        if isinstance(costs, list):
            for cost in costs:
                if not isinstance(cost, dict):
                    continue
                description = str(cost.get("description") or "").lower()
                if "tipping" not in description and "tip" not in description:
                    continue
                total += abs(_Utils.parse_decimal(cost.get("amount")))
        return int(total)

    @staticmethod
    def get_amount_details_tip_amount(payload):
        """Get tip amount directly from the amount_details block.

        :param dict payload: The notification payload.
        :return: Tip amount.
        :rtype: Decimal
        """
        if not isinstance(payload, dict):
            return Decimal("0")

        amount_details = payload.get("amount_details")
        if not isinstance(amount_details, dict):
            return Decimal("0")

        tip = amount_details.get("tip")
        if isinstance(tip, dict):
            return abs(_Utils.parse_decimal(tip.get("amount")))
        return Decimal("0")

    @classmethod
    def add_terminal_tip_warning(cls, latest_response, payload):
        """Flag and warning annotate mismatched tip amounts in the payment response.

        :param dict latest_response: The dictionary structure being built for latest response.
        :param dict payload: The raw notification payload.
        """
        remote_tip_amount = cls.get_remote_tip_amount(payload)
        if not remote_tip_amount:
            return

        odoo_tip_amount = int(latest_response.get("odoo_tip_amount_cents") or 0)
        unmatched_tip_amount = max(remote_tip_amount - odoo_tip_amount, 0)

        latest_response["remote_tip_amount_cents"] = remote_tip_amount
        latest_response["terminal_tip_unmatched"] = bool(unmatched_tip_amount)
        latest_response["terminal_tip_unmatched_amount_cents"] = unmatched_tip_amount
        if not unmatched_tip_amount:
            return

        latest_response["terminal_tip_detected"] = True
        latest_response["terminal_tip_amount_cents"] = unmatched_tip_amount
        latest_response["terminal_tip_amount"] = unmatched_tip_amount
        latest_response["warning"] = _(
            "A terminal-side tip was detected in MultiSafepay. Tips must be added "
            "in Odoo so the POS order, shopping cart and accounting stay aligned."
        )
        _logger.warning(
            "MSP Cloud POS terminal-side tip detected for order %s: "
            "terminal_tip_amount_cents=%s, odoo_tip_amount_cents=%s",
            latest_response.get("order_id") or latest_response.get("id"),
            unmatched_tip_amount,
            odoo_tip_amount,
        )
