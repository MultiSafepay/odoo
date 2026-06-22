# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from ..helpers.order_context_builder import (
    _OrderContextBuilder,
)
from ..helpers.status import _Status


class _OdooPayloadBuilder:
    """Build dictionaries for Odoo model create/write operations.

    This class handles the complex task of preparing field values for database operations
    (create and write) on the tracking payment records. Extracting this responsibility
    keeps the core Odoo models lean and focuses them on business logic rather than
    data formatting, strictly following the Single Responsibility Principle.
    """

    @staticmethod
    def create_values(response, data, terminal_id, status):
        """Prepare values to create a new tracking payment record in Odoo.

        :param dict response: The SDK response when initializing the order.
        :param dict data: The initial checkout data sent by the POS frontend.
        :param str terminal_id: The ID of the terminal processing the request.
        :param str status: The initial normalized status.
        :return: A dictionary of field values for pos.multisafepay.cloud.payment creation.
        :rtype: dict
        """
        payload = response | {"status": status}
        payload.setdefault("state", _Status.state(status))
        payload.update(_OrderContextBuilder.from_payload(data))

        values = {
            "name": response.get("order_id") or response.get("id"),
            "msp_cloud_uid": data.get("msp_cloud_uid"),
            "msp_cloud_attempt_base": data.get("msp_cloud_attempt_base"),
            "msp_cloud_attempt_number": data.get("msp_cloud_attempt_number") or 0,
            "payment_method_id": data.get("payment_method_id"),
            "session_id": data.get("session_id"),
            "terminal_id": terminal_id,
            "events_token": response.get("events_token") or response.get("event_token"),
            "remote_transaction_id": response.get("transaction_id")
            or response.get("order_id"),
            "events_stream_url": response.get("events_stream_url")
            or response.get("event_stream_url"),
            "last_event_id": response.get("last_event_id"),
            "msp_latest_response": payload,
            "status": status,
        }
        if response.get("receipt"):
            values["receipt_data"] = response.get("receipt")
        return values

    @staticmethod
    def write_for_cancel(payment, cancellation):
        """Prepare write values to persist a successful cancellation.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :param dict cancellation: The cancellation response details.
        :return: A dictionary of field values for Odoo write operations.
        :rtype: dict
        """
        status = _Status.normalize(cancellation.get("status") or "canceled")
        payload = (
            (payment.msp_latest_response or {})
            | cancellation
            | {
                "status": status,
                "state": _Status.state(status),
                "order_id": payment.name,
                "transaction_id": cancellation.get("transaction_id")
                or payment.remote_transaction_id
                or payment.name,
            }
        )
        return {
            "msp_latest_response": payload,
            "status": status,
            "remote_transaction_id": payload["transaction_id"],
            "stream_state": "done",
            "stream_lock_until": False,
        }

    @staticmethod
    def write_for_refund(payment, refund, status, reversal_action):
        """Prepare write and status payload values for a successful refund.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :param dict refund: The refund response details from MultiSafepay.
        :param str status: The local status target for this refund.
        :param str reversal_action: Reversal action type description.
        :return: A tuple of write values dictionary and updated status response dictionary.
        :rtype: tuple[dict, dict]
        """
        status = _Status.normalize(status or refund.get("status") or "refunded")
        refund_transaction_id = (
            refund.get("refund_id")
            or refund.get("transaction_id")
            or refund.get("id")
            or payment.refund_transaction_id
        )
        payload = (payment.msp_latest_response or {}) | {
            "status": status,
            "state": "success",
            "order_id": payment.name,
            "transaction_id": payment.remote_transaction_id or payment.name,
            "refund": refund,
            "refund_id": refund_transaction_id,
            "reversal_action": reversal_action,
        }
        write_vals = {
            "msp_latest_response": payload,
            "status": status,
            "refund_transaction_id": refund_transaction_id,
            "stream_state": "done",
            "stream_lock_until": False,
        }
        return write_vals, payload

    @classmethod
    def write_for_notification(cls, payment, payload, method, now_string):
        """Prepare write and status response values for a notification webhook.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :param dict payload: The notification payload.
        :param str method: The HTTP request method (e.g. 'POST', 'GET').
        :param str now_string: String representation of current timestamp.
        :return: A tuple of write values dictionary and updated latest response dictionary.
        :rtype: tuple[dict, dict]
        """
        status = _Status.normalize(payload.get("status") or payment.status)
        state = _Status.state(status)
        transaction_id = cls._extract_transaction_id(payload, payment)

        latest_response = (payment.msp_latest_response or {}) | {
            "status": status,
            "state": state,
            "order_id": payment.name,
            "transaction_id": transaction_id,
            "last_notification": payload,
            "notification_method": method,
            "notification_received_at": now_string,
        }
        for key in (
            "last_status_refresh_error",
            "last_status_refresh_error_at",
            "last_status_refresh_error_source",
        ):
            latest_response.pop(key, None)

        write_vals = {
            "status": status,
            "remote_transaction_id": transaction_id,
            "stream_state": "done" if state != "pending" else payment.stream_state,
            "stream_lock_until": False
            if state != "pending"
            else payment.stream_lock_until,
        }

        cls._append_events(payload, write_vals, latest_response)
        return write_vals, latest_response

    @staticmethod
    def _extract_transaction_id(payload, payment):
        """Extract transaction ID from payload or fallback to payment record.

        :param dict payload: The notification payload.
        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :return: The transaction ID.
        :rtype: str
        """
        return (
            payload.get("transaction_id")
            or payload.get("transactionid")
            or payload.get("transactionId")
            or payload.get("id")
            or payment.remote_transaction_id
            or payment.name
        )

    @staticmethod
    def _append_events(payload, write_vals, latest_response):
        """Append event-related data to write values and latest response dictionaries.

        :param dict payload: The notification payload.
        :param dict write_vals: The write values dictionary to update.
        :param dict latest_response: The latest response dictionary to update.
        """
        event_id = payload.get("last_event_id") or payload.get("event_id")
        if event_id:
            write_vals["last_event_id"] = latest_response["last_event_id"] = event_id

        token = payload.get("events_token") or payload.get("event_token")
        if token:
            write_vals["events_token"] = latest_response["events_token"] = token

        stream_url = payload.get("events_stream_url") or payload.get("event_stream_url")
        if stream_url:
            write_vals["events_stream_url"] = latest_response["events_stream_url"] = (
                stream_url
            )

    @staticmethod
    def write_for_refresh_error(payment, remote_status, source, now_string):
        """Prepare write values when status retrieval fails.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :param dict remote_status: The SDK response of the error.
        :param str source: The context identifier of the check operation.
        :param str now_string: String representation of current timestamp.
        :return: A dictionary containing the updated latest response.
        :rtype: dict
        """
        current_status = _Status.normalize(payment.status)
        latest_response = (payment.msp_latest_response or {}) | {
            "status": current_status,
            "state": _Status.state(current_status),
            "order_id": payment.name,
            "transaction_id": payment.remote_transaction_id or payment.name,
            "last_status_refresh_error": remote_status,
            "last_status_refresh_error_at": now_string,
            "last_status_refresh_error_source": source,
        }
        return {"msp_latest_response": latest_response}

    @staticmethod
    def determine_refund_status(amount=None, source_payment=None):
        """Determine whether a refund status should be refunded or partially refunded.

        :param float/str amount: The refund amount requested.
        :param pos.payment source_payment: The original POS payment record.
        :return: 'partial_refunded' or 'refunded'.
        :rtype: str
        """
        if not source_payment:
            return "refunded"

        currency = source_payment.currency_id
        refund_amount = abs(float(amount or 0.0))
        source_amount = abs(float(source_payment.amount or 0.0))
        if currency and currency.compare_amounts(refund_amount, source_amount) < 0:
            return "partial_refunded"
        return "refunded"

    @staticmethod
    def write_for_cancel_error(payment, cancellation):
        """Prepare write and status payload when order cancellation fails.

        :param pos.multisafepay.cloud.payment payment: The local tracking payment record.
        :param dict cancellation: The failed cancellation response.
        :return: A tuple of write values dictionary and error payload dictionary.
        :rtype: tuple[dict, dict]
        """
        payload = (
            (payment.msp_latest_response or {})
            | cancellation
            | {
                "order_id": payment.name,
                "transaction_id": payment.remote_transaction_id or payment.name,
            }
        )
        write_vals = {
            "msp_latest_response": payload,
            "status": "error",
            "stream_state": "error",
            "stream_lock_until": False,
        }
        return write_vals, payload

    @staticmethod
    def write_for_reversal_error(refund):
        """Prepare write values when refund/reversal fails.

        :param dict refund: The failed refund response.
        :return: A dictionary to save the reversal response.
        :rtype: dict
        """
        return {"reversal_response": refund}
