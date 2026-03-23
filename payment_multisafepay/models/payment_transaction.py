# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging
import pprint
import uuid
from decimal import Decimal

from multisafepay.api.paths.orders.order_id.refund.request.refund_request import (
    RefundOrderRequest,
)
from multisafepay.api.shared.cart.cart_item import CartItem
from multisafepay.api.shared.description import Description
from multisafepay.value_object.currency import Currency

from odoo import _, models
from odoo.exceptions import UserError

from .. import const
from ..utils import money_to_minor_units, minor_units_to_money

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """MultiSafepay Payment Transaction.

    Extends Odoo's payment.transaction model to add MultiSafepay-specific functionality
    including transaction processing, status mapping, and refund handling.
    """

    _inherit = "payment.transaction"

    # ===================================
    # FIELDS
    # ===================================

    # Note: multisafepay_refund_reason field moved to payment_multisafepay_enhanced (custom feature)

    # ===================================
    # BUSINESS METHODS (ODOO)
    # ===================================

    def _get_specific_processing_values(self, processing_values):
        """Override to return specific processing values for MultiSafepay.

        :param processing_values: The generic processing values
        :return: MultiSafepay-specific processing values
        :rtype: dict
        """
        self.ensure_one()

        res = super()._get_specific_processing_values(processing_values)

        if self.provider_code != "multisafepay":
            return res

        _logger.debug("Input processing values: %s", str(processing_values))

        res.update(
            {
                "reference": self.reference,
            }
        )

        _logger.debug("Final processing values: %s", str(res))

        return res

    def _get_specific_rendering_values(self, processing_values):
        """Override to return specific rendering values for MultiSafepay.

        :param processing_values: The generic processing values
        :return: MultiSafepay-specific rendering values
        :rtype: dict
        """
        self.ensure_one()

        res = super()._get_specific_rendering_values(processing_values)

        if self.provider_code != "multisafepay":
            return res

        return processing_values

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """Override of payment to find the transaction based on MultiSafepay data.

        :param provider_code: The code of the provider that handled the transaction
        :param notification_data: The notification data sent by the provider
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raises ValidationError: If inconsistent data were received
        :raises ValidationError: If the data match no transaction
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != "multisafepay" or len(tx) == 1:
            return tx

        reference = notification_data.get("reference")
        if reference:
            tx = self.search(
                [("reference", "=", reference), ("provider_code", "=", "multisafepay")]
            )

        return tx

    def _process_notification_data(self, notification_data):
        """Override of `payment` to process the transaction based on MultiSafepay data.

        :param notification_data: The notification data sent by MultiSafepay
        :return: None
        """
        self.ensure_one()

        # Fix: Odoo 19 compatibility - parent class doesn't have _process_notification_data
        # Handle notification processing directly without calling super()
        if self.provider_code != "multisafepay":
            return

        transaction_id = notification_data.get("reference")
        if transaction_id and not self.provider_reference:
            self.write({"provider_reference": transaction_id})
            _logger.debug("Updated provider_reference to: %s", transaction_id)

        status = notification_data.get("status")
        # If it's already a native Odoo state, return it directly
        odoo_native_states = [
            "draft",
            "pending",
            "authorized",
            "done",
            "cancel",
            "error",
        ]
        if status in odoo_native_states:
            _logger.debug("Status '%s' is native Odoo state - using as-is", status)
            odoo_state = status
        else:
            odoo_state = self._get_multisafepay_status_to_odoo_state(status)

        if odoo_state == "draft":
            _logger.debug(
                "MSP status '%s' → keeping transaction in draft (ref=%s)",
                status,
                self.reference,
            )

        elif odoo_state == "done":
            _logger.debug(
                "MSP status '%s' → marking transaction done (ref=%s)",
                status,
                self.reference,
            )
            # Fix: Odoo 19 compatibility - _set_done() no longer accepts message parameter
            self._set_done()

        elif odoo_state == "cancel":
            _logger.debug(
                "MSP status '%s' → canceling transaction (ref=%s)",
                status,
                self.reference,
            )
            # Fix: Odoo 19 compatibility - _set_canceled() no longer accepts message parameter
            self._set_canceled()

        elif odoo_state == "error":
            _logger.debug(
                "MSP status '%s' → setting transaction to error (ref=%s)",
                status,
                self.reference,
            )
            # Fix: Odoo 19 compatibility - _set_error() no longer accepts message parameter
            self._set_error()

        elif odoo_state == "pending":
            _logger.debug(
                "MSP status '%s' → setting transaction to pending (ref=%s)",
                status,
                self.reference,
            )
            # Fix: Odoo 19 compatibility - _set_pending() no longer accepts message parameter
            self._set_pending()

        elif odoo_state == "partial_refunded":
            _logger.debug(
                "MSP status '%s' → payment partially refunded (ref=%s)",
                status,
                self.reference,
            )
            # Fix: Odoo 19 compatibility - _set_done() no longer accepts message parameter
            self._set_done()

        _logger.info("Transaction %s updated to state '%s'", self.reference, odoo_state)

    # Note: _create_child_transaction override moved to payment_multisafepay_enhanced
    # (handles multisafepay_refund_reason custom field)

    def _send_refund_request(self, amount_to_refund=0.0):
        """Override of payment to send a refund request to MultiSafepay.

        :param amount_to_refund: The amount to refund (default: 0.0)
        :return: None
        :raises UserError: If refund fails or validation errors occur
        """
        self.ensure_one()

        if self.provider_code != "multisafepay":
            return super()._send_refund_request()

        # In Odoo 19, self is already the refund transaction
        # Get the original transaction via source_transaction_id
        if not self.source_transaction_id:
            raise UserError(
                _(
                    "Refunds can only be processed from a refund transaction linked to an original payment transaction."
                )
            )

        original_tx = self.source_transaction_id
        original_reference = original_tx.reference
        amount_to_refund = abs(self.amount)

        provider = self.provider_id
        multisafepay_sdk = provider.get_multisafepay_sdk()
        order_manager = multisafepay_sdk.get_order_manager()

        try:
            # Get current order status from MultiSafepay using original reference
            order_response = order_manager.get(original_reference)
            order_data = order_response.get_data()
        except Exception as api_error:
            _logger.error(
                "API error retrieving order %s: %s", original_reference, str(api_error)
            )
            raise UserError(
                _(
                    "Could not connect to MultiSafepay API for transaction %s.\n\nError: %s"
                )
                % (self.reference, str(api_error))
            )

        if not order_data:
            _logger.error("Could not retrieve order data for %s", self.reference)
            raise UserError(
                _(
                    "Could not retrieve order information from MultiSafepay for transaction %s.\n\nReference: %s\nProvider: %s\n\nPlease check your internet connection and try again later."
                )
                % (self.reference, original_reference, self.provider_id.name)
            )

        original_amount = abs(original_tx.amount)
        # Check order status
        order_status = getattr(order_data, "status", "")

        # Early check: if already refunded, don't proceed
        if order_status == "refunded":
            _logger.info("Order %s is already refunded", original_reference)
            raise UserError(
                _(
                    "This order has already been fully refunded.\n\nTransaction: %s\nOrder Status: %s\nOriginal Amount: %.2f %s\n\nNo additional refunds can be processed."
                )
                % (
                    original_reference,
                    order_status,
                    abs(amount_to_refund),
                    self.currency_id.name,
                )
            )

        remaining_amount = 0
        if hasattr(order_data, "amount_refunded") and order_data.amount_refunded:
            _logger.warning(
                "Order %s has already been partially refunded", original_reference
            )

            # Use Decimal for precise monetary calculations to avoid floating-point errors
            refunded_decimal = Decimal(str(order_data.amount_refunded))
            refunded_amount = minor_units_to_money(
                refunded_decimal, self.currency_id
            )
            remaining_amount = original_amount - refunded_amount

        if remaining_amount and amount_to_refund > remaining_amount:
            _logger.error(
                "Refund amount %s exceeds remaining amount %s for order %s",
                amount_to_refund,
                remaining_amount,
                original_reference,
            )
            raise UserError(
                _(
                    "Refund amount exceeds available amount.\n\nTransaction: %s\nRequested Refund: %.2f %s\nMaximum Available: %.2f %s\nAlready Refunded: %.2f %s\n\nPlease adjust the refund amount."
                )
                % (
                    original_reference,
                    abs(amount_to_refund),
                    self.currency_id.name,
                    remaining_amount,
                    self.currency_id.name,
                    refunded_amount,
                    self.currency_id.name,
                )
            )

        try:
            amount_in_gateway_units = money_to_minor_units(
                abs(amount_to_refund), self.currency_id
            )

            refund_response = None
            is_bnpl = (
                original_tx.payment_method_code.removeprefix(
                    const.PAYMENT_METHOD_PREFIX
                )
                in const.BNPL_METHODS
            )

            try:
                if is_bnpl:
                    refund_request = order_manager.create_refund_request(order_data)
                    cart_item = (
                        CartItem(**{})
                        .add_merchant_item_id(str(uuid.uuid4()))
                        .add_name(f"Refund for Odoo order {original_reference}")
                        .add_quantity(1)
                        .add_unit_price(-amount_to_refund)
                        .add_tax_table_selector("0")
                    )
                    refund_request.checkout_data.add_item(cart_item)
                    refund_payload = RefundOrderRequest(**{}).add_checkout_data(
                        refund_request.checkout_data
                    )

                else:
                    refund_payload = (
                        RefundOrderRequest(**{})
                        .add_amount(amount_in_gateway_units)
                        .add_currency(Currency(currency=self.currency_id.name).currency)
                        .add_description(
                            Description(**{}).add_description(
                                f"Refund for Odoo order {original_reference}"
                            )
                        )
                    )

                _logger.debug(
                    "Refund payload for order %s: %s",
                    original_reference,
                    str(refund_payload.dict()),
                )

                refund_response = order_manager.refund(
                    original_reference, refund_payload
                )
            except Exception:
                refund_response = False

            if not refund_response:
                _logger.error(
                    "No response received from MultiSafepay for refund of order %s",
                    original_reference,
                )
                raise UserError(
                    _(
                        "No response received from MultiSafepay when attempting to refund transaction %s.\n\nPlease check your internet connection and try again later."
                    )
                    % original_reference
                )

            refund_data = refund_response.get_data()
            _logger.info("Refund response data: %s", pprint.pformat(refund_data))

            _logger.debug("Refund response data: %s", str(refund_data))

            success_refund = False
            if is_bnpl:
                success_refund = refund_response.body.get("success", False)
            else:
                success_refund = refund_data and hasattr(refund_data, "transaction_id")

            if not success_refund:
                error_msg = None
                if refund_data:
                    for attr in (
                        "error_info",
                        "message",
                        "description",
                        "detail",
                        "error",
                    ):
                        if hasattr(refund_data, attr):
                            error_msg = getattr(refund_data, attr)
                            break

                if (
                    not error_msg
                    and hasattr(refund_response, "body")
                    and refund_response.body
                ):
                    for attr in (
                        "error_info",
                        "message",
                        "description",
                        "detail",
                        "error",
                    ):
                        error_value = refund_response.body.get(attr)
                        if error_value:
                            error_msg = error_value
                            break

                if error_msg:
                    _logger.error("Refund failed for %s: %s", self.reference, error_msg)
                    raise UserError(
                        _("Refund failed at MultiSafepay: %s\n") % error_msg
                    )

                _logger.error(
                    "Something went wrong with refund for order %s", self.reference
                )
                raise UserError(
                    _("Refund failed at MultiSafepay: %s\n") % self.reference
                )

            # Update refund transaction with provider reference
            if refund_data and hasattr(refund_data, "transaction_id"):
                self.provider_reference = refund_data.transaction_id

            # Mark refund as successful
            notification_data = {
                "status": "completed",
                "amount": amount_to_refund,
                "currency": self.currency_id.name,
            }
            if refund_data and hasattr(refund_data, "transaction_id"):
                notification_data["reference"] = refund_data.transaction_id

            self._process_notification_data(notification_data)

        except Exception as e:
            _logger.error(
                "Something went wrong with refund for order %s: %s",
                self.reference,
                str(e),
            )
            raise UserError(str(e))

    # ===================================
    # MULTISAFEPAY - Helpers
    # ===================================

    def _get_multisafepay_status_to_odoo_state(self, multisafepay_status: str) -> str:
        """Map a MultiSafepay status to its corresponding Odoo transaction state.

        This function performs a reverse lookup on the STATUS_MAPPING constant to find
        the Odoo state (key) that corresponds to a given MultiSafepay status (value
        within the tuple).

        :param multisafepay_status: The status received from MultiSafepay (e.g., 'completed', 'uncleared')
        :return: The corresponding Odoo state (e.g., 'done', 'pending'). Defaults to 'error'
        :rtype: str
        """
        for odoo_state, msp_statuses in const.STATUS_MAPPING.items():
            if multisafepay_status in msp_statuses:
                return odoo_state

        return "error"
