# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import requests

from odoo import _


class _ErrorPayload:
    """Build POS-facing error payloads from Cloud POS API failures.

    This class is responsible for converting complex SDK, HTTP, and generic exceptions
    into clean, readable dictionaries formatted specifically for the Odoo POS frontend.
    Extracting this into a separate class isolates the error-parsing logic from the main
    payment flow, ensuring that the core code remains clean and adheres to the Single Responsibility Principle.
    """

    @staticmethod
    def format_exception(error):
        """Convert SDK, HTTP and generic exceptions into readable details.

        :param error: Exception object or string error.
        :return: Human readable error message details.
        :rtype: str
        """
        if not error:
            return ""
        if isinstance(error, str):
            return error

        if isinstance(error, requests.HTTPError):
            response = getattr(error, "response", None)
            if response is not None:
                try:
                    payload = response.json() or {}
                except ValueError:
                    payload = {}

                error_info = (payload.get("error_info") or "").strip()
                error_code = payload.get("error_code")
                if error_info and error_code:
                    return f"{error_info} (error_code: {error_code})"
                if error_info:
                    return error_info

        error_message = str(error).strip()
        error_type = type(error).__name__
        return f"{error_type}: {error_message}" if error_message else error_type

    @classmethod
    def build(cls, payment_method_or_detail, default_detail=None, error=None, operation=None):
        """Build a POS-friendly error payload for Cloud POS API failures.

        Can be called with a simple text message:
        `build("My simple error message")`

        Or with an exception and context to humanize:
        `build(payment_method, "Fallback message", error=e, operation="status")`

        :param payment_method_or_detail: The payment method record, or a plain string message.
        :param str default_detail: Local fallback message (if first argument is a payment method).
        :param error: Triggering exception or SDK error code payload.
        :param str operation: Label identifying the failing operation (e.g. 'status').
        :return: Normalized POS-facing error response.
        :rtype: dict
        """
        if default_detail is None and isinstance(payment_method_or_detail, str):
            final_detail = payment_method_or_detail
        else:
            final_detail = cls.humanize(
                payment_method_or_detail,
                cls.format_exception(error),
                default_detail,
                operation=operation,
            ) or default_detail

        return {
            "status": "error",
            "state": "failure",
            "detail": final_detail,
        }

    @staticmethod
    def humanize(payment_method, detail, default_detail, operation=None):
        """Translate low-level API details into actionable POS messages.

        :param pos.payment.method payment_method: The associated payment method.
        :param str detail: Low-level API detail error description.
        :param str default_detail: Local fallback message.
        :param str operation: Label identifying the failing operation.
        :return: Translated POS-facing detail error description.
        :rtype: str
        """
        normalized_detail = (detail or "").strip()
        if not normalized_detail:
            return default_detail

        normalized_detail_lower = normalized_detail.lower()

        if (
            "connectexception" in normalized_detail_lower
            or "connectionerror" in normalized_detail_lower
        ):
            return _(
                "Could not connect to the MultiSafepay Cloud POS API. Please check your internet connection."
            )

        if (
            "timeout" in normalized_detail_lower
            or "timed out" in normalized_detail_lower
        ):
            return _(
                "The MultiSafepay Cloud POS terminal did not return a final result in time. "
                "Check the terminal status before retrying the payment."
            )

        if "No API key configured for terminal_group_id" in normalized_detail:
            terminal_group_id = (
                payment_method.msp_cloud_terminal_group_id or ""
            ).strip()
            if terminal_group_id:
                return _(
                    "Cloud POS authentication failed for Terminal Group ID "
                    "'%(terminal_group_id)s'. Verify the Terminal Group API Key "
                    "on the payment method."
                ) % {"terminal_group_id": terminal_group_id}
            return _(
                "Cloud POS authentication failed. Verify Terminal Group ID and "
                "Terminal Group API Key on the payment method."
            )

        if "Missing terminal_group_id in auth scope" in normalized_detail:
            return _(
                "Cloud POS authentication failed because Terminal Group ID is "
                "missing on the payment method."
            )

        if "Invalid transaction ID" in normalized_detail:
            if operation == "status":
                return _(
                    "The MultiSafepay Cloud POS payment is no longer available as an active terminal transaction. "
                    "It may have timed out or been cancelled on the terminal. Check the terminal before retrying."
                )
            if operation == "cancel":
                return _(
                    "The MultiSafepay Cloud POS payment could not be cancelled because the terminal transaction is no longer available. "
                    "It may already be cancelled or expired."
                )
            return _(
                "MultiSafepay Cloud POS could not start this payment attempt. "
                "The previous terminal transaction may still be active, expired, or already cancelled. Check the terminal before retrying."
            )

        return normalized_detail
