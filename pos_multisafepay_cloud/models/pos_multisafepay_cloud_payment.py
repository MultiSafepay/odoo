# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

"""Odoo model for tracking MultiSafepay Cloud POS payment attempts."""

import logging

from odoo import _, api, fields, models

from ..helpers.frontend_response_builder import (
    _FrontendResponseBuilder,
)
from ..helpers.notification_payload import (
    _NotificationPayload,
)
from ..helpers.odoo_payload_builder import (
    _OdooPayloadBuilder,
)
from ..helpers.status import _Status

_logger = logging.getLogger(__name__)


class PosMultiSafepayCloudPayment(models.Model):
    """Model for tracking and managing MultiSafepay Cloud POS payment attempts.

    This model acts as a backend bridge and state machine between Odoo POS and the
    MultiSafepay Cloud POS API. It tracks individual payment attempts, status transitions,
    terminal receipts, webhook notifications, cancellations, voids, and refunds
    independently of native Odoo POS orders.

    Key Functional Components:

    1. Public Interface & Workflow Entry Points:
       - `create_payment_request`: Creates and initializes a local tracking payment record.
       - `multisafepay_cloud_rpc_poll_payment_status`: Retrieves the latest status of an active terminal payment request.
       - `multisafepay_cloud_rpc_cancel_payment_request`: Cancels an ongoing payment request on the terminal.
       - `multisafepay_cloud_rpc_reverse_payment_request`: Triggers a void or reversal for an uncompleted transaction.
       - `multisafepay_cloud_rpc_refund_payment_request`: Processes full or partial refunds for completed payments.

    2. Status Synchronization & Webhook Processing:
       - `_force_remote_status_check`: Forces a live remote API call to update local transaction state.
       - `_record_status_refresh_error`: Handles and logs errors occurring during status checks.
       - `_apply_notification_payload`: Updates payment state from incoming MultiSafepay webhooks.
       - `_cancel_missing_payment_request`: Handles cancellation when remote record is uninitialized.
       - `_find_payment`: Utility to locate tracking records by order ID or Cloud UID.
       - `_find_source_pos_payment`: Identifies original POS payment records for refund processing.
       - `_refresh_status`: Queries the MultiSafepay API to refresh and sync transaction status.

    3. Transaction Mechanics & Lifecycle Actions:
       - `_cancel_payment_request`: Executes the cancellation API call and updates state.
       - `_reverse_payment_request`: Executes payment reversal logic with MultiSafepay.
       - `_refund_payment_request`: Performs refund API operations and links refund transactions.
       - `_mark_as_canceled`: Updates internal status and response payloads to canceled state.
       - `_mark_as_refunded`: Updates internal status and response payloads to refunded state.
       - `_build_status_payload`: Formats the standard status dictionary returned to the POS frontend.
    """

    _name = "pos.multisafepay.cloud.payment"
    _description = "PoS MultiSafepay Cloud Payment"
    _order = "id desc"

    name = fields.Char("Cloud POS Order ID", required=True)
    msp_cloud_uid = fields.Char("Cloud UID", index=True)
    msp_cloud_attempt_base = fields.Char("Attempt Base", index=True)
    msp_cloud_attempt_number = fields.Integer("Attempt Number", default=0, index=True)
    payment_method_id = fields.Many2one("pos.payment.method", required=True)
    session_id = fields.Many2one("pos.session")
    terminal_id = fields.Char("Terminal ID")
    remote_transaction_id = fields.Char("Remote Transaction ID")
    msp_latest_response = fields.Json("Response", default=dict)
    receipt_data = fields.Json(default=dict)
    status = fields.Selection(
        [
            ("initialized", "Initialized"),
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("paid", "Paid"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("declined", "Declined"),
            ("expired", "Expired"),
            ("canceled", "Canceled"),
            ("void", "Void"),
            ("refunded", "Refunded"),
            ("partial_refunded", "Partially Refunded"),
            ("error", "Error"),
        ],
        default="initialized",
    )
    refund_transaction_id = fields.Char("Refund Transaction ID", copy=False)
    reversal_response = fields.Json(default=dict)
    reversed_at = fields.Datetime(copy=False)
    events_token = fields.Char(copy=False)
    events_stream_url = fields.Char("Events Stream URL", copy=False)
    last_event_id = fields.Char("Last Event ID", copy=False)
    stream_state = fields.Selection(
        [
            ("idle", "Idle"),
            ("streaming", "Streaming"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="idle",
        copy=False,
    )
    stream_lock_until = fields.Datetime(copy=False)

    @api.model
    def create_payment_request(self, response, data):
        """Initialize and create a local tracking payment record.

        :param dict response: The SDK initialization response.
        :param dict data: The checkout parameters from the POS.
        :return: A new pos.multisafepay.cloud.payment record or False.
        :rtype: pos.multisafepay.cloud.payment or bool
        """
        if not response:
            return False

        status = _Status.normalize(response.get("status") or "initialized")
        if status == "error":
            return False

        payment_method = self.env["pos.payment.method"].browse(
            data.get("payment_method_id")
        )
        currency = payment_method._get_cloud_pos_currency(data.get("currency"))
        values = _OdooPayloadBuilder.create_values(
            response,
            data,
            payment_method.msp_cloud_terminal_id,
            status,
            currency,
        )

        _logger.info(
            "Created MultiSafepay Cloud POS payment tracker for order %s (Remote ID: %s, Status: %s).",
            values.get("name"),
            values.get("remote_transaction_id"),
            status,
        )

        return self.sudo().create(values)

    @api.model
    def multisafepay_cloud_rpc_poll_payment_status(self, order_id=None, msp_cloud_uid=None):
        """Handle a status request for a Cloud POS payment, updating it if pending.

        [FRONTEND RPC ENTRYPOINT]
        Primary polling endpoint invoked directly by POS JavaScript frontend.

        :param str order_id: The Cloud POS order ID.
        :param str msp_cloud_uid: The Cloud UID reference.
        :return: A POS-facing dictionary representing current payment status.
        :rtype: dict
        """
        payment = self._find_payment(order_id=order_id, msp_cloud_uid=msp_cloud_uid)
        if not payment:
            return {}

        # The frontend only polls Odoo's local state, expecting the webhook to update the database.
        # if _Status.state(payment.status) == "pending":
        #     payment._refresh_status()

        return payment._build_status_payload()

    @api.model
    def multisafepay_cloud_rpc_cancel_payment_request(
        self, order_id=None, msp_cloud_uid=None, payment_method_id=None
    ):
        """Handle cancellation of a Cloud POS payment.

        [FRONTEND RPC ENTRYPOINT]
        Cancellation endpoint invoked directly by POS JavaScript frontend.

        :param str order_id: The Cloud POS order ID.
        :param str msp_cloud_uid: The Cloud UID reference.
        :param int payment_method_id: The ID of the payment method.
        :return: POS-facing response payload.
        :rtype: dict
        """
        payment = self._find_payment(order_id=order_id, msp_cloud_uid=msp_cloud_uid)
        if not payment:
            cancellation = self._cancel_missing_payment_request(
                msp_cloud_uid=msp_cloud_uid,
                payment_method_id=payment_method_id,
            )
            if cancellation:
                return cancellation
            return _FrontendResponseBuilder.error(
                _("Could not find the MultiSafepay Cloud POS payment to cancel.")
            )
        return payment._cancel_payment_request()

    @api.model
    def multisafepay_cloud_rpc_reverse_payment_request(
        self, order_id=None, msp_cloud_uid=None, amount=None, currency=None
    ):
        """Handle reversal of a paid Cloud POS payment.

        [FRONTEND RPC ENTRYPOINT]
        Reversal endpoint invoked directly by POS JavaScript frontend.

        :param str order_id: The Cloud POS order ID.
        :param str msp_cloud_uid: The Cloud UID reference.
        :param float amount: The refund/reversal amount.
        :param str currency: The currency code.
        :return: POS-facing response payload.
        :rtype: dict
        """
        payment = self._find_payment(order_id=order_id, msp_cloud_uid=msp_cloud_uid)
        if not payment:
            return _FrontendResponseBuilder.error(
                _("Could not find the MultiSafepay Cloud POS payment to reverse.")
            )
        return payment._reverse_payment_request(amount=amount, currency=currency)

    @api.model
    def multisafepay_cloud_rpc_refund_payment_request(
        self,
        refunded_payment_id=None,
        order_id=None,
        msp_cloud_uid=None,
        amount=None,
        currency=None,
    ):
        """Process and request a refund for an original payment.

        [FRONTEND RPC ENTRYPOINT]
        Refund endpoint invoked directly by POS JavaScript frontend.

        :param str/int refunded_payment_id: The original pos.payment ID.
        :param str order_id: The Cloud POS order ID.
        :param str msp_cloud_uid: The Cloud UID reference.
        :param float amount: The refund amount.
        :param str currency: The currency code.
        :return: POS-facing response payload.
        :rtype: dict
        """
        source_payment = self._find_source_pos_payment(refunded_payment_id)
        if source_payment:
            order_id = (
                order_id
                or source_payment.transaction_id
                or source_payment.payment_ref_no
            )
            msp_cloud_uid = msp_cloud_uid or order_id

        payment = self._find_payment(
            order_id=order_id,
            msp_cloud_uid=msp_cloud_uid,
            include_remote=True,
        )
        if not payment:
            return _FrontendResponseBuilder.error(
                _(
                    "Could not find the original MultiSafepay Cloud POS payment to refund."
                )
            )
        return payment._refund_payment_request(
            amount=amount,
            currency=currency,
            source_payment=source_payment,
        )

    def _force_remote_status_check(self, method=None):
        """Fetch remote order status and apply it as a notification update.

        :param str method: Request source tag/method name.
        :return: Status response dictionary.
        :rtype: dict
        """
        self.ensure_one()

        remote_status = self.payment_method_id._api_get_cloud_order_status(self.name)
        if not remote_status:
            return self._build_status_payload()

        if (
            remote_status.get("state") == "failure"
            and remote_status.get("status") == "error"
        ):
            self._record_status_refresh_error(
                remote_status, source=(method or "status_refresh")
            )
            return self._build_status_payload()

        self._apply_notification_payload(remote_status, method=method)
        return self._build_status_payload()

    def _record_status_refresh_error(self, remote_status, source="status_refresh"):
        """Record an error that occurred while refreshing the order status.

        :param dict remote_status: The error payload returned by the SDK.
        :param str source: Context identifying the source of the error.
        """
        self.ensure_one()
        now_string = fields.Datetime.to_string(fields.Datetime.now())
        write_vals = _OdooPayloadBuilder.write_for_refresh_error(
            self, remote_status, source, now_string
        )
        self.sudo().write(write_vals)

    def _apply_notification_payload(self, payload, method=None):
        """Apply a notification or remote status payload to the payment record.

        :param dict payload: MultiSafepay notification or order status payload.
        :param str method: HTTP method or source label of the notification.
        """
        self.ensure_one()
        now_string = fields.Datetime.to_string(fields.Datetime.now())
        write_vals, latest_response = _OdooPayloadBuilder.write_for_notification(
            self, payload, method, now_string
        )
        _NotificationPayload.add_terminal_tip_warning(latest_response, payload)
        write_vals["msp_latest_response"] = latest_response

        if latest_response.get("state") == "success" and not self.receipt_data:
            receipt_data = self.payment_method_id._api_get_cloud_receipt(self.name)
            if receipt_data:
                write_vals["receipt_data"] = receipt_data

        _logger.info(
            "MultiSafepay Cloud POS payment %s updated (Method: %s). New Status: %s (State: %s)",
            self.name,
            method or "unknown",
            write_vals.get("status", self.status),
            latest_response.get("state", "unknown"),
        )

        self.sudo().write(write_vals)

    def _cancel_missing_payment_request(
        self, msp_cloud_uid=None, payment_method_id=None
    ):
        """Cancel a remote order that has no local tracking record.

        :param str msp_cloud_uid: The Cloud UID reference.
        :param int payment_method_id: The pos.payment.method ID.
        :return: Cancellation API response payload.
        :rtype: dict
        """
        if not (msp_cloud_uid and payment_method_id):
            return {}

        payment_method = (
            self.env["pos.payment.method"].sudo().browse(payment_method_id).exists()
        )
        if not payment_method:
            return {}

        return payment_method._api_cancel_cloud_pos_order(msp_cloud_uid)

    def _find_payment(self, order_id=None, msp_cloud_uid=None, include_remote=False):
        """Locate tracked payment records using known identifiers.

        :param str order_id: The order ID reference.
        :param str msp_cloud_uid: The Cloud UID reference.
        :param bool include_remote: Whether to search by remote_transaction_id.
        :return: A pos.multisafepay.cloud.payment record (which might be empty).
        :rtype: pos.multisafepay.cloud.payment
        """
        references = [reference for reference in (msp_cloud_uid, order_id) if reference]
        if not references:
            return self.browse()

        for reference in references:
            if include_remote:
                domain = [
                    "|",
                    "|",
                    ("name", "=", reference),
                    ("remote_transaction_id", "=", reference),
                    ("msp_cloud_uid", "=", reference),
                ]
            else:
                domain = [
                    "|",
                    ("msp_cloud_uid", "=", reference),
                    ("name", "=", reference),
                ]
            payment = self.sudo().search(domain, limit=1)
            if payment:
                return payment
        return self.browse()

    def _find_source_pos_payment(self, refunded_payment_id=None):
        """Locate the original payment line.

        :param int/str refunded_payment_id: The pos.payment record ID.
        :return: A pos.payment record (which might be empty).
        :rtype: pos.payment
        """
        if not refunded_payment_id:
            return self.env["pos.payment"].browse()
        try:
            refunded_payment_id = int(refunded_payment_id)
        except (TypeError, ValueError):
            return self.env["pos.payment"].browse()
        return self.env["pos.payment"].sudo().browse(refunded_payment_id).exists()

    def _refresh_status(self):
        """Fetch status updates via API status endpoints and update database."""
        self.ensure_one()

        sdk = self.payment_method_id._get_multisafepay_cloud_sdk()

        event_payload = self.payment_method_id._api_get_cloud_order_status(
            self.name,
            sdk=sdk,
        )
        if event_payload and event_payload.get("status"):
            status = _Status.normalize(event_payload.get("status") or self.status)
            values = {
                "msp_latest_response": {
                    **(self.msp_latest_response or {}),
                    **event_payload,
                    "status": status,
                    "state": _Status.state(status),
                },
                "status": status,
                "remote_transaction_id": event_payload.get("transaction_id")
                or self.remote_transaction_id,
            }

            if _Status.state(status) == "success" and not self.receipt_data:
                receipt_data = self.payment_method_id._api_get_cloud_receipt(
                    self.name,
                    sdk=sdk,
                )
                if receipt_data:
                    values["receipt_data"] = receipt_data

            self.sudo().write(values)
            if _Status.state(status) != "pending":
                return

        if not (self.payment_method_id.msp_cloud_account_api_key or "").strip():
            return

        remote_status = self.payment_method_id._api_get_cloud_order_status(
            self.name,
            sdk=sdk,
        )
        if not remote_status:
            return

        if (
            remote_status.get("state") == "failure"
            and remote_status.get("status") == "error"
        ):
            self._record_status_refresh_error(remote_status)
            return

        status = _Status.normalize(remote_status.get("status") or self.status)
        values = {
            "msp_latest_response": {
                **remote_status,
                "status": status,
                "state": _Status.state(status),
            },
            "status": status,
            "remote_transaction_id": remote_status.get("transaction_id")
            or self.remote_transaction_id,
        }

        if _Status.state(status) == "success" and not self.receipt_data:
            receipt_data = self.payment_method_id._api_get_cloud_receipt(
                self.name,
                sdk=sdk,
            )
            if receipt_data:
                values["receipt_data"] = receipt_data

        self.sudo().write(values)

    def _cancel_payment_request(self):
        """Cancel a tracked Cloud POS payment order.

        :return: POS-facing response payload.
        :rtype: dict
        """
        self.ensure_one()

        status_state = _Status.state(self.status)
        if status_state == "success":
            return _FrontendResponseBuilder.payment_error(
                self,
                status=self.status,
                state="success",
                detail=_(
                    "The MultiSafepay Cloud POS payment is already paid and cannot be cancelled."
                ),
            )

        if self.status in {"canceled", "expired", "failed", "declined", "void"}:
            return self._build_status_payload()

        cancellation = self.payment_method_id._api_cancel_cloud_pos_order(self.name)
        if cancellation.get("status") == "error":
            write_vals, payload = _OdooPayloadBuilder.write_for_cancel_error(
                self, cancellation
            )
            self.sudo().write(write_vals)
            _logger.warning(
                "MultiSafepay Cloud POS payment cancellation failed for %s.", self.name
            )
            return payload

        _logger.info(
            "MultiSafepay Cloud POS payment %s was successfully cancelled.", self.name
        )
        return self._mark_as_canceled(cancellation)

    def _reverse_payment_request(self, amount=None, currency=None):
        """Initiate reversal actions for a tracked payment.

        :param float amount: The reversal amount.
        :param str currency: The currency code.
        :return: POS-facing response payload.
        :rtype: dict
        """
        self.ensure_one()

        if _Status.state(self.status) == "pending":
            self._refresh_status()

        if self.status in {"refunded", "partial_refunded"}:
            payload = self._build_status_payload()
            payload.update({"state": "success", "reversal_action": "refund"})
            return payload

        if _Status.state(self.status) == "pending":
            cancellation = self._cancel_payment_request()
            if cancellation.get("status") in {
                "canceled",
                "expired",
                "failed",
                "declined",
                "void",
            }:
                cancellation.update({"state": "success", "reversal_action": "cancel"})
            return cancellation

        if _Status.state(self.status) != "success":
            return _FrontendResponseBuilder.payment_error(
                self,
                status=self.status,
                state="failure",
                detail=_("Only paid MultiSafepay Cloud POS payments can be reversed."),
            )

        refund = self.payment_method_id._api_refund_cloud_pos_order(
            self.name,
            amount=amount,
            currency=currency,
            description=_("POS reversal for #%(order_id)s") % {"order_id": self.name},
        )
        if refund.get("status") == "error":
            self.sudo().write(_OdooPayloadBuilder.write_for_reversal_error(refund))
            return refund

        return self._mark_as_refunded(refund)

    def _refund_payment_request(self, amount=None, currency=None, source_payment=None):
        """Initiate refund actions for a tracked paid payment.

        :param float amount: The refund amount.
        :param str currency: The currency code.
        :param pos.payment source_payment: The original payment record.
        :return: POS-facing response payload.
        :rtype: dict
        """
        self.ensure_one()

        if self.status == "refunded":
            return _FrontendResponseBuilder.payment_error(
                self,
                status="refunded",
                state="failure",
                detail=_(
                    "The original MultiSafepay Cloud POS payment is already fully refunded."
                ),
            )

        if _Status.state(self.status) == "pending":
            self._refresh_status()

        if _Status.state(self.status) != "success":
            return _FrontendResponseBuilder.payment_error(
                self,
                status=self.status,
                state="failure",
                detail=_("Only paid MultiSafepay Cloud POS payments can be refunded."),
            )

        refund_status = _OdooPayloadBuilder.determine_refund_status(
            amount, source_payment
        )

        refund = self.payment_method_id._api_refund_cloud_pos_order(
            self.name,
            amount=amount,
            currency=currency,
            description=_("POS refund for #%(order_id)s") % {"order_id": self.name},
        )
        if refund.get("status") == "error":
            self.sudo().write(_OdooPayloadBuilder.write_for_reversal_error(refund))
            return refund

        return self._mark_as_refunded(
            refund,
            status=refund_status,
            reversal_action="refund",
        )

    def _mark_as_canceled(self, cancellation):
        """Persist a successful cancellation response.

        :param dict cancellation: Normalized cancellation response payload.
        :return: POS-facing status payload after the write.
        :rtype: dict
        """
        self.ensure_one()
        write_vals = _OdooPayloadBuilder.write_for_cancel(self, cancellation)
        self.sudo().write(write_vals)
        return self._build_status_payload()

    def _mark_as_refunded(self, refund, status="refunded", reversal_action="refund"):
        """Persist a refund response.

        :param dict refund: Normalized refund response payload.
        :param str status: Local status to store for the payment.
        :param str reversal_action: POS reversal action label to return.
        :return: POS-facing refund payload after the write.
        :rtype: dict
        """
        self.ensure_one()
        write_vals, payload = _OdooPayloadBuilder.write_for_refund(
            self, refund, status, reversal_action
        )
        write_vals["reversal_response"] = refund
        write_vals["reversed_at"] = fields.Datetime.now()
        self.sudo().write(write_vals)
        return payload

    def _build_status_payload(self):
        """Build status dictionary for POS frontend.

        :return: POS status response payload.
        :rtype: dict
        """
        self.ensure_one()
        return _FrontendResponseBuilder.response(self)
