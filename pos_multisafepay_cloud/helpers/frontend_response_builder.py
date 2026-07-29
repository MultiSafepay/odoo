# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from error_payload import (
    _ErrorPayload,
)

from .status import _Status


class _FrontendResponseBuilder:
    """Build dictionaries for the POS frontend.

    This class centralizes the logic required to format API and system responses into
    dictionaries that the Odoo POS frontend expects. By isolating this responsibility,
    the core payment model is decoupled from frontend data structure requirements,
    promoting maintainability and the Single Responsibility Principle.
    """

    @staticmethod
    def response(payment):
        """Build a POS-friendly dictionary representing the payment status.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :return: A dictionary representing the current status, state, and other transaction details.
        :rtype: dict
        """
        latest_response = payment.msp_latest_response or {}
        status = _Status.normalize(latest_response.get("status") or payment.status)

        payload = latest_response | {
            "id": payment.remote_transaction_id or payment.name,
            "order_id": payment.name,
            "transaction_id": payment.remote_transaction_id or payment.name,
            "msp_cloud_attempt_base": payment.msp_cloud_attempt_base,
            "msp_cloud_attempt_number": payment.msp_cloud_attempt_number,
            "status": status,
            "state": _Status.state(status),
        }

        if payment.receipt_data and "receipt" not in payload:
            payload["receipt"] = payment.receipt_data

        return payload

    @staticmethod
    def error(detail, status_code=None, extra=None):
        """Build an HTTP error response for the frontend.

        :param str detail: Error explanation.
        :param int status_code: HTTP response status code (default 400).
        :param dict extra: Additional payload properties.
        :return: HTTP response payload.
        :rtype: dict
        """
        error = _ErrorPayload.build(detail)
        if status_code is not None:
            error["status_code"] = status_code
        if extra:
            error.update(extra)
        return error

    @staticmethod
    def payment_error(payment, status, state, detail):
        """Build a dictionary representing an error with current payment context.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :param str status: The current status of the payment.
        :param str state: The state of the payment (e.g., 'failure', 'success').
        :param str detail: A description of the cancellation or refund error.
        :return: A payment error payload.
        :rtype: dict
        """
        return {
            "status": status,
            "state": state,
            "detail": detail,
            "order_id": payment.name,
            "transaction_id": payment.remote_transaction_id or payment.name,
        }
