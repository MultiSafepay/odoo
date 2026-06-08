import logging
from decimal import Decimal, InvalidOperation

from multisafepay.util.webhook import Webhook

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PosMultiSafepayCloudPayment(models.Model):
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
    msp_latest_response = fields.Json("Response", default={})
    receipt_data = fields.Json("Receipt Data", default={})
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
    reversal_response = fields.Json("Reversal Response", default={})
    reversed_at = fields.Datetime("Reversed At", copy=False)
    events_token = fields.Char("Events Token", copy=False)
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
    stream_lock_until = fields.Datetime("Stream Lock Until", copy=False)

    @api.model
    def create_payment_request(self, response, data):
        if not response:
            return False

        status = self._normalize_status(response.get("status") or "initialized")
        if status == "error":
            return False

        payment_method = self.env["pos.payment.method"].browse(data.get("payment_method_id"))

        payload = dict(response)
        payload["status"] = status
        payload.setdefault("state", self._status_state(status))
        payload.update(self._build_odoo_request_metadata(data))

        return self.sudo().create(
            {
                "name": response.get("order_id") or response.get("id"),
                "msp_cloud_uid": data.get("msp_cloud_uid"),
                "msp_cloud_attempt_base": data.get("msp_cloud_attempt_base"),
                "msp_cloud_attempt_number": data.get("msp_cloud_attempt_number") or 0,
                "payment_method_id": data.get("payment_method_id"),
                "session_id": data.get("session_id"),
                "terminal_id": payment_method.msp_cloud_terminal_id,
                "events_token": response.get("events_token") or response.get("event_token"),
                "remote_transaction_id": response.get("transaction_id") or response.get("order_id"),
                "events_stream_url": response.get("events_stream_url") or response.get("event_stream_url"),
                "last_event_id": response.get("last_event_id"),
                "msp_latest_response": payload,
                "status": status,
                **({"receipt_data": response.get("receipt")} if response.get("receipt") else {}),
            }
        )

    def _build_odoo_request_metadata(self, data):
        shopping_cart = data.get("shopping_cart") if isinstance(data, dict) else None
        items = shopping_cart.get("items") if isinstance(shopping_cart, dict) else []
        if not isinstance(items, list):
            items = []

        cart_amount = Decimal("0")
        tip_amount = Decimal("0")
        tip_line_count = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            unit_price = self._decimal_from_payload(item.get("unit_price"))
            quantity = self._decimal_from_payload(item.get("quantity") or 0)
            item_amount = abs(unit_price * quantity)
            cart_amount += item_amount
            if item.get("msp_cloud_is_tip"):
                tip_amount += item_amount
                tip_line_count += 1

        return {
            "odoo_order_amount": data.get("amount") if isinstance(data, dict) else None,
            "odoo_shopping_cart_item_count": len(items),
            "odoo_shopping_cart_amount": float(cart_amount),
            "odoo_shopping_cart_amount_cents": self._major_amount_to_cents(cart_amount),
            "odoo_tip_amount": float(tip_amount),
            "odoo_tip_amount_cents": self._major_amount_to_cents(tip_amount),
            "odoo_tip_line_count": tip_line_count,
        }

    @api.model
    def _major_amount_to_cents(self, value):
        return int((value * Decimal("100")).quantize(Decimal("1")))

    @api.model
    def _decimal_from_payload(self, value):
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    @api.model
    def get_payment_status(self, order_id=None, msp_cloud_uid=None):
        payment = self._find_payment(order_id=order_id, msp_cloud_uid=msp_cloud_uid)
        if not payment:
            return {}

        if payment._status_state(payment.status) == "pending":
            payment._refresh_status()

        return payment._build_status_payload()

    @api.model
    def cancel_payment_request(self, order_id=None, msp_cloud_uid=None, payment_method_id=None):
        payment = self._find_payment(order_id=order_id, msp_cloud_uid=msp_cloud_uid)
        if not payment:
            cancellation = self._cancel_missing_payment_request(
                msp_cloud_uid=msp_cloud_uid,
                payment_method_id=payment_method_id,
            )
            if cancellation:
                return cancellation
            return {
                "status": "error",
                "state": "failure",
                "detail": _("Could not find the MultiSafepay Cloud POS payment to cancel."),
            }
        return payment._cancel_payment_request()

    @api.model
    def reverse_payment_request(self, order_id=None, msp_cloud_uid=None, amount=None, currency=None):
        payment = self._find_payment(order_id=order_id, msp_cloud_uid=msp_cloud_uid)
        if not payment:
            return {
                "status": "error",
                "state": "failure",
                "detail": _("Could not find the MultiSafepay Cloud POS payment to reverse."),
            }
        return payment._reverse_payment_request(amount=amount, currency=currency)

    @api.model
    def refund_payment_request(
        self,
        refunded_payment_id=None,
        order_id=None,
        msp_cloud_uid=None,
        amount=None,
        currency=None,
    ):
        source_payment = self._find_source_pos_payment(refunded_payment_id)
        if source_payment:
            order_id = order_id or source_payment.transaction_id or source_payment.payment_ref_no
            msp_cloud_uid = msp_cloud_uid or order_id

        payment = self._find_payment(
            order_id=order_id,
            msp_cloud_uid=msp_cloud_uid,
            include_remote=True,
        )
        if not payment:
            return {
                "status": "error",
                "state": "failure",
                "detail": _("Could not find the original MultiSafepay Cloud POS payment to refund."),
            }
        return payment._refund_payment_request(
            amount=amount,
            currency=currency,
            source_payment=source_payment,
        )

    @api.model
    def process_notification(
        self,
        payload,
        raw_body=None,
        auth_header=None,
        method=None,
    ):
        method_name = (method or "").upper()
        notification_payload = payload if isinstance(payload, dict) else {}
        reference = self._get_notification_reference(notification_payload)
        if not reference:
            return {
                "status": "error",
                "state": "failure",
                "status_code": 400,
                "detail": _("The MultiSafepay Cloud POS notification has no order reference."),
                "notification": notification_payload,
            }

        payment = self._find_payment(
            order_id=reference,
            msp_cloud_uid=reference,
            include_remote=True,
        )
        if not payment:
            return {
                "status": "error",
                "state": "failure",
                "status_code": 404,
                "detail": _("No MultiSafepay Cloud POS payment was found for this notification."),
                "order_id": reference,
                "notification": notification_payload,
            }

        if not payment.payment_method_id._msp_cloud_allows_webhook_confirmation(method):
            _logger.info(
                "MSP Cloud POS notification ignored for order %s because payment method %s uses confirmation channel %s.",
                payment.name,
                payment.payment_method_id.display_name,
                payment.payment_method_id._msp_cloud_confirmation_channel_value(),
            )
            return payment._build_status_payload()

        if not payment._validate_notification_auth(raw_body, auth_header):
            return {
                "status": "error",
                "state": "failure",
                "status_code": 403,
                "detail": _("The MultiSafepay Cloud POS notification signature is invalid."),
                "order_id": payment.name,
            }

        if method_name == "GET":
            return payment._force_remote_status_check(method=method_name)

        status_payload = notification_payload
        if not notification_payload.get("status"):
            remote_status = payment.payment_method_id._api_get_cloud_order_status(payment.name)
            if remote_status and remote_status.get("state") != "failure":
                status_payload = {**notification_payload, **remote_status}

        payment._apply_notification_payload(status_payload, method=method)
        return payment._build_status_payload()

    @api.model
    def _get_notification_reference(self, payload):
        for key in (
            "order_id",
            "orderid",
            "orderId",
            "transactionid",
            "transaction_id",
            "transactionId",
            "reference",
            "id",
            "msp_cloud_uid",
        ):
            reference = payload.get(key)
            if reference:
                return str(reference)
        return ""

    def _validate_notification_auth(self, raw_body=None, auth_header=None):
        self.ensure_one()
        if not raw_body or not auth_header:
            return True

        api_keys = []
        for api_key in (
            self.payment_method_id.msp_cloud_terminal_group_api_key,
            self.payment_method_id.msp_cloud_account_api_key,
        ):
            api_key = (api_key or "").strip()
            if api_key and api_key not in api_keys:
                api_keys.append(api_key)

        if not api_keys:
            _logger.warning(
                "MSP Cloud POS notification for order %s has an Auth header, but no API key is configured to validate it.",
                self.name,
            )
            return False

        validation_error = None
        for api_key in api_keys:
            try:
                if Webhook.validate(
                    request=raw_body,
                    auth=auth_header,
                    api_key=api_key,
                    validation_time_in_seconds=600,
                ):
                    return True
            except Exception as error:
                validation_error = error

        if validation_error:
            _logger.warning(
                "MSP Cloud POS notification signature validation failed for order %s with %s configured API key(s): %s",
                self.name,
                len(api_keys),
                validation_error,
            )
        return False

    def _force_remote_status_check(self, method=None):
        self.ensure_one()

        remote_status = self.payment_method_id._api_get_cloud_order_status(self.name)
        if not remote_status:
            return self._build_status_payload()

        if (
            remote_status.get("state") == "failure"
            and remote_status.get("status") == "error"
        ):
            self._record_status_refresh_error(remote_status, source=(method or "status_refresh"))
            return self._build_status_payload()

        self._apply_notification_payload(remote_status, method=method)
        return self._build_status_payload()

    def _record_status_refresh_error(self, remote_status, source="status_refresh"):
        self.ensure_one()

        current_status = self._normalize_status(self.status)
        now_string = fields.Datetime.to_string(fields.Datetime.now())
        latest_response = dict(self.msp_latest_response or {})
        latest_response.update(
            {
                "status": current_status,
                "state": self._status_state(current_status),
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
                "last_status_refresh_error": remote_status,
                "last_status_refresh_error_at": now_string,
                "last_status_refresh_error_source": source,
            }
        )
        self.sudo().write({"msp_latest_response": latest_response})

    def _apply_notification_payload(self, payload, method=None):
        self.ensure_one()

        status = self._normalize_status(payload.get("status") or self.status)
        state = self._status_state(status)
        transaction_id = (
            payload.get("transaction_id")
            or payload.get("transactionid")
            or payload.get("transactionId")
            or payload.get("id")
            or self.remote_transaction_id
            or self.name
        )
        now_string = fields.Datetime.to_string(fields.Datetime.now())

        latest_response = dict(self.msp_latest_response or {})
        latest_response.update(
            {
                "status": status,
                "state": state,
                "order_id": self.name,
                "transaction_id": transaction_id,
                "last_notification": payload,
                "notification_method": method,
                "notification_received_at": now_string,
            }
        )
        latest_response.pop("last_status_refresh_error", None)
        latest_response.pop("last_status_refresh_error_at", None)
        latest_response.pop("last_status_refresh_error_source", None)
        self._add_terminal_tip_warning(latest_response, payload)

        values = {
            "msp_latest_response": latest_response,
            "status": status,
            "remote_transaction_id": transaction_id,
            "stream_state": "done" if state != "pending" else self.stream_state,
            "stream_lock_until": False if state != "pending" else self.stream_lock_until,
        }

        last_event_id = payload.get("last_event_id") or payload.get("event_id")
        if last_event_id:
            values["last_event_id"] = last_event_id
            latest_response["last_event_id"] = last_event_id

        events_token = payload.get("events_token") or payload.get("event_token")
        if events_token:
            values["events_token"] = events_token
            latest_response["events_token"] = events_token

        events_stream_url = payload.get("events_stream_url") or payload.get("event_stream_url")
        if events_stream_url:
            values["events_stream_url"] = events_stream_url
            latest_response["events_stream_url"] = events_stream_url

        if state == "success" and not self.receipt_data:
            receipt_data = self.payment_method_id._api_get_cloud_receipt(self.name)
            if receipt_data:
                values["receipt_data"] = receipt_data

        self.sudo().write(values)

    def _add_terminal_tip_warning(self, latest_response, payload):
        remote_tip_amount = self._remote_tip_amount_from_payload(payload)
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
            self.name,
            unmatched_tip_amount,
            odoo_tip_amount,
        )

    @api.model
    def _remote_tip_amount_from_payload(self, payload):
        amount_details_tip = self._remote_amount_details_tip_amount(payload)
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
                total += abs(self._decimal_from_payload(cost.get("amount")))
        return int(total)

    @api.model
    def _remote_amount_details_tip_amount(self, payload):
        if not isinstance(payload, dict):
            return Decimal("0")

        amount_details = payload.get("amount_details")
        if not isinstance(amount_details, dict):
            return Decimal("0")

        tip = amount_details.get("tip")
        if isinstance(tip, dict):
            return abs(self._decimal_from_payload(tip.get("amount")))
        return Decimal("0")

    def _cancel_missing_payment_request(self, msp_cloud_uid=None, payment_method_id=None):
        if not (msp_cloud_uid and payment_method_id):
            return {}

        payment_method = self.env["pos.payment.method"].sudo().browse(payment_method_id).exists()
        if not payment_method:
            return {}

        return payment_method._api_cancel_cloud_pos_order(msp_cloud_uid)

    def _find_payment(self, order_id=None, msp_cloud_uid=None, include_remote=False):
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
        if not refunded_payment_id:
            return self.env["pos.payment"].browse()
        try:
            refunded_payment_id = int(refunded_payment_id)
        except (TypeError, ValueError):
            return self.env["pos.payment"].browse()
        return self.env["pos.payment"].sudo().browse(refunded_payment_id).exists()

    def _refresh_status(self):
        self.ensure_one()

        sdk = self.payment_method_id._get_multisafepay_cloud_sdk()

        event_payload = self.payment_method_id._wait_for_cloud_order_event(
            sdk,
            self.msp_latest_response or {},
            timeout_seconds=self.payment_method_id.msp_cloud_timeout_seconds or 60,
            last_event_id=(self.msp_latest_response or {}).get("last_event_id"),
        )
        if event_payload:
            status = self._normalize_status(event_payload.get("status") or self.status)
            values = {
                "msp_latest_response": {
                    **(self.msp_latest_response or {}),
                    **event_payload,
                    "status": status,
                    "state": self._status_state(status),
                },
                "status": status,
                "remote_transaction_id": event_payload.get("transaction_id") or self.remote_transaction_id,
            }

            if self._status_state(status) == "success" and not self.receipt_data:
                receipt_data = self.payment_method_id._api_get_cloud_receipt(
                    self.name,
                    sdk=sdk,
                )
                if receipt_data:
                    values["receipt_data"] = receipt_data

            self.sudo().write(values)
            if self._status_state(status) != "pending":
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

        status = self._normalize_status(remote_status.get("status") or self.status)
        values = {
            "msp_latest_response": {
                **remote_status,
                "status": status,
                "state": self._status_state(status),
            },
            "status": status,
            "remote_transaction_id": remote_status.get("transaction_id") or self.remote_transaction_id,
        }

        if self._status_state(status) == "success" and not self.receipt_data:
            receipt_data = self.payment_method_id._api_get_cloud_receipt(
                self.name,
                sdk=sdk,
            )
            if receipt_data:
                values["receipt_data"] = receipt_data

        self.sudo().write(values)

    def _cancel_payment_request(self):
        self.ensure_one()

        status_state = self._status_state(self.status)
        if status_state == "success":
            return {
                "status": self.status,
                "state": "success",
                "detail": _(
                    "The MultiSafepay Cloud POS payment is already paid and cannot be cancelled."
                ),
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
            }

        if self.status in {"canceled", "expired", "failed", "declined", "void"}:
            return self._build_status_payload()

        cancellation = self.payment_method_id._api_cancel_cloud_pos_order(self.name)
        if cancellation.get("status") == "error":
            payload = {
                **(self.msp_latest_response or {}),
                **cancellation,
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
            }
            self.sudo().write(
                {
                    "msp_latest_response": payload,
                    "status": "error",
                    "stream_state": "error",
                    "stream_lock_until": False,
                }
            )
            return payload

        return self._mark_as_canceled(cancellation)

    def _reverse_payment_request(self, amount=None, currency=None):
        self.ensure_one()

        if self._status_state(self.status) == "pending":
            self._refresh_status()

        if self.status in {"refunded", "partial_refunded"}:
            payload = self._build_status_payload()
            payload.update({"state": "success", "reversal_action": "refund"})
            return payload

        if self._status_state(self.status) == "pending":
            cancellation = self._cancel_payment_request()
            if cancellation.get("status") in {"canceled", "expired", "failed", "declined", "void"}:
                cancellation.update({"state": "success", "reversal_action": "cancel"})
            return cancellation

        if self._status_state(self.status) != "success":
            return {
                "status": self.status,
                "state": "failure",
                "detail": _("Only paid MultiSafepay Cloud POS payments can be reversed."),
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
            }

        refund = self.payment_method_id._api_refund_cloud_pos_order(
            self.name,
            amount=amount,
            currency=currency,
            description=_("POS reversal for %(order_id)s") % {"order_id": self.name},
        )
        if refund.get("status") == "error":
            self.sudo().write({"reversal_response": refund})
            return refund

        return self._mark_as_refunded(refund)

    def _refund_payment_request(self, amount=None, currency=None, source_payment=None):
        self.ensure_one()

        if self.status == "refunded":
            return {
                "status": "refunded",
                "state": "failure",
                "detail": _("The original MultiSafepay Cloud POS payment is already fully refunded."),
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
            }

        if self._status_state(self.status) == "pending":
            self._refresh_status()

        if self._status_state(self.status) != "success":
            return {
                "status": self.status,
                "state": "failure",
                "detail": _("Only paid MultiSafepay Cloud POS payments can be refunded."),
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
            }

        refund_status = self._refund_status_for_amount(amount, source_payment)

        refund = self.payment_method_id._api_refund_cloud_pos_order(
            self.name,
            amount=amount,
            currency=currency,
            description=_("POS refund for %(order_id)s") % {"order_id": self.name},
        )
        if refund.get("status") == "error":
            self.sudo().write({"reversal_response": refund})
            return refund

        return self._mark_as_refunded(
            refund,
            status=refund_status,
            reversal_action="refund",
        )

    def _refund_status_for_amount(self, amount=None, source_payment=None):
        if not source_payment:
            return "refunded"

        currency = source_payment.currency_id
        refund_amount = abs(float(amount or 0.0))
        source_amount = abs(float(source_payment.amount or 0.0))
        if currency and currency.compare_amounts(refund_amount, source_amount) < 0:
            return "partial_refunded"
        return "refunded"

    def _mark_as_canceled(self, cancellation):
        self.ensure_one()

        status = self._normalize_status(cancellation.get("status") or "canceled")
        payload = {
            **(self.msp_latest_response or {}),
            **cancellation,
            "status": status,
            "state": self._status_state(status),
            "order_id": self.name,
            "transaction_id": cancellation.get("transaction_id")
            or self.remote_transaction_id
            or self.name,
        }
        self.sudo().write(
            {
                "msp_latest_response": payload,
                "status": status,
                "remote_transaction_id": payload["transaction_id"],
                "stream_state": "done",
                "stream_lock_until": False,
            }
        )
        return self._build_status_payload()

    def _mark_as_refunded(self, refund, status="refunded", reversal_action="refund"):
        self.ensure_one()

        status = self._normalize_status(status or refund.get("status") or "refunded")
        refund_transaction_id = (
            refund.get("refund_id")
            or refund.get("transaction_id")
            or refund.get("id")
            or self.refund_transaction_id
        )
        payload = {
            **(self.msp_latest_response or {}),
            "status": status,
            "state": "success",
            "order_id": self.name,
            "transaction_id": self.remote_transaction_id or self.name,
            "refund": refund,
        }
        self.sudo().write(
            {
                "msp_latest_response": payload,
                "status": status,
                "refund_transaction_id": refund_transaction_id,
                "reversal_response": refund,
                "reversed_at": fields.Datetime.now(),
                "stream_state": "done",
                "stream_lock_until": False,
            }
        )
        payload.update(
            {
                "refund_id": refund_transaction_id,
                "reversal_action": reversal_action,
            }
        )
        return payload

    def _build_status_payload(self):
        self.ensure_one()

        payload = dict(self.msp_latest_response or {})
        status = self._normalize_status(payload.get("status") or self.status)
        payload.update(
            {
                "id": self.remote_transaction_id or self.name,
                "order_id": self.name,
                "transaction_id": self.remote_transaction_id or self.name,
                "msp_cloud_attempt_base": self.msp_cloud_attempt_base,
                "msp_cloud_attempt_number": self.msp_cloud_attempt_number,
                "status": status,
                "state": self._status_state(status),
            }
        )
        if self.receipt_data:
            payload.setdefault("receipt", self.receipt_data)
        return payload

    @api.model
    def _normalize_status(self, status):
        normalized = (status or "initialized").lower()
        status_map = {
            "created": "initialized",
            "waiting": "pending",
            "authorised": "processing",
            "authorized": "processing",
            "cancelled": "canceled",
            "success": "paid",
            "reversed": "refunded",
        }
        return status_map.get(normalized, normalized)

    @api.model
    def _status_state(self, status):
        normalized = self._normalize_status(status)
        if normalized in {"paid", "completed", "refunded", "partial_refunded"}:
            return "success"
        if normalized in {"failed", "declined", "expired", "canceled", "void", "error"}:
            return "failure"
        return "pending"
