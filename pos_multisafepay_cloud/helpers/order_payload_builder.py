# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from decimal import Decimal, InvalidOperation

from multisafepay.api.paths.orders.request.components import AmountDetails, Tip
from multisafepay.api.paths.orders.request.components.checkout_options import (
    CheckoutOptions as CheckoutOptionsRequest,
)
from multisafepay.api.shared.cart.cart_item import CartItem
from multisafepay.api.shared.cart.shopping_cart import ShoppingCart
from multisafepay.api.shared.checkout.checkout_options import (
    CheckoutOptions as CheckoutOptionsTaxTables,
)
from multisafepay.api.shared.checkout.default_tax_rate import DefaultTaxRate
from multisafepay.api.shared.checkout.tax_rate import TaxRate
from multisafepay.api.shared.checkout.tax_rule import TaxRule
from multisafepay.api.shared.customer import Customer

from odoo import _

from ..helpers.utils import (
    _Utils,
)


class _OrderPayloadBuilder:
    """Build SDK order request components from POS payment payloads.

    This class is responsible for constructing the complex request structures
    (shopping carts, customer details, terminal routing) required by the MultiSafepay SDK.
    Separating this logic ensures the Single Responsibility Principle is followed,
    keeping the API interaction cleanly separated from payload construction.
    """

    @classmethod
    def shopping_cart(cls, payment_method, shopping_cart_data):
        """Build a MultiSafepay shopping cart from POS cart data.

        :param pos.payment.method payment_method: The associated payment method record.
        :param dict shopping_cart_data: Cart payload dictionary.
        :return: SDK ShoppingCart structure or None.
        :rtype: multisafepay.api.shared.cart.shopping_cart.ShoppingCart or None
        """
        if not isinstance(shopping_cart_data, dict):
            return None

        items_data = (shopping_cart_data or {}).get("items")
        if not isinstance(items_data, list):
            return None

        cart_items = []
        for item_data in items_data:
            item = cls.cart_item(payment_method, item_data)
            if item:
                cart_items.append(item)

        return ShoppingCart(items=cart_items) if cart_items else None

    @classmethod
    def amount_details(cls, shopping_cart_data):
        """Build amount details such as tips for the Cloud POS request.

        :param dict shopping_cart_data: Cart payload dictionary.
        :return: AmountDetails structure or None.
        :rtype: multisafepay.api.paths.orders.request.components.AmountDetails or None
        """
        tip_amount = cls.shopping_cart_tip_amount(shopping_cart_data)
        tip_amount_in_cents = _Utils.amount_to_minor_units(tip_amount)
        if tip_amount_in_cents <= 0:
            return None

        return AmountDetails().add_tip(Tip().add_amount(tip_amount_in_cents))

    @staticmethod
    def shopping_cart_tip_amount(shopping_cart_data):
        """Calculate the tip amount represented in POS shopping cart lines.

        :param dict shopping_cart_data: Cart payload dictionary.
        :return: Calculated tip amount.
        :rtype: Decimal
        """
        if not isinstance(shopping_cart_data, dict):
            return Decimal("0")

        items_data = shopping_cart_data.get("items")
        if not isinstance(items_data, list):
            return Decimal("0")

        tip_amount = Decimal("0")
        for item_data in items_data:
            if not isinstance(item_data, dict) or not item_data.get("msp_cloud_is_tip"):
                continue

            unit_price = _Utils.parse_decimal(item_data.get("unit_price"))
            quantity = _Utils.parse_decimal(item_data.get("quantity") or 0)
            tip_amount += abs(unit_price * quantity)

        return tip_amount

    @classmethod
    def cart_item(cls, payment_method, item_data):
        """Convert a POS cart item payload into a MultiSafepay cart item.

        :param pos.payment.method payment_method: The associated payment method record.
        :param dict item_data: Cart item payload dictionary.
        :return: CartItem SDK object or None.
        :rtype: multisafepay.api.shared.cart.cart_item.CartItem or None
        """
        if not isinstance(item_data, dict):
            return None

        quantity = item_data.get("quantity") or 0
        if not quantity:
            return None

        item = cls._initialize_cart_item(payment_method, item_data, quantity)
        cls._apply_cart_item_taxes(item, item_data)

        return item

    @staticmethod
    def _initialize_cart_item(payment_method, item_data, quantity):
        """Initialize the cart item with basic attributes.

        :param pos.payment.method payment_method: The associated payment method record.
        :param dict item_data: Cart item payload dictionary.
        :param float|int quantity: The quantity of the item.
        :return: Initialized CartItem SDK object.
        :rtype: multisafepay.api.shared.cart.cart_item.CartItem
        """
        name = str(item_data.get("name") or _("POS item"))[:255]
        merchant_item_id = _Utils.sanitize_order_id(
            item_data.get("merchant_item_id") or name,
            payment_method.id,
        )
        item = (
            CartItem(**{})
            .add_name(name)
            .add_description(str(item_data.get("description") or "")[:255])
            .add_unit_price(item_data.get("unit_price") or 0)
            .add_quantity(quantity)
            .add_merchant_item_id(merchant_item_id)
        )
        if item_data.get("currency"):
            item.add_currency(str(item_data.get("currency")))
        if isinstance(item_data.get("options"), list):
            item.add_options(item_data.get("options"))
        return item

    @staticmethod
    def _apply_cart_item_taxes(cart_item, item_data):
        """Apply tax rules or percentages to a cart item.

        :param multisafepay.api.shared.cart.cart_item.CartItem cart_item: The SDK cart item.
        :param dict item_data: Cart item payload dictionary containing tax information.
        """
        tax_rate_percentage = item_data.get("tax_rate_percentage")
        if tax_rate_percentage is not None:
            cart_item.add_tax_rate(_Utils.tax_rate_from_percentage(tax_rate_percentage))
        elif item_data.get("tax_table_selector") is not None:
            cart_item.add_tax_table_selector(str(item_data.get("tax_table_selector")))
        else:
            cart_item.add_tax_rate(Decimal("0"))

    @classmethod
    def customer(cls, customer_data):
        """Convert POS customer data into a MultiSafepay customer payload.

        :param dict customer_data: POS customer payload dictionary.
        :return: Customer SDK object or None.
        :rtype: multisafepay.api.shared.customer.Customer or None
        """
        if not isinstance(customer_data, dict):
            return None

        first_name, last_name = cls._extract_customer_names(customer_data)
        truncate_text = _Utils.truncate_text

        customer_values = {
            "locale": truncate_text(customer_data.get("locale"), 16),
            "reference": truncate_text(customer_data.get("reference"), 255),
            "first_name": first_name,
            "last_name": last_name,
            "address1": truncate_text(customer_data.get("address1"), 255),
            "address2": truncate_text(customer_data.get("address2"), 255),
            "house_number": truncate_text(customer_data.get("house_number"), 64),
            "zip_code": truncate_text(customer_data.get("zip_code"), 64),
            "city": truncate_text(customer_data.get("city"), 255),
            "state": truncate_text(customer_data.get("state"), 255),
            "country": _Utils.format_country_code(customer_data.get("country")),
            "phone": truncate_text(customer_data.get("phone"), 64),
            "email": _Utils.format_email(customer_data.get("email")),
        }
        customer_values = {
            key: value for key, value in customer_values.items() if value
        }
        return Customer(**customer_values) if customer_values else None

    @staticmethod
    def _extract_customer_names(customer_data):
        """Extract and format the first and last name from customer data.

        :param dict customer_data: POS customer payload dictionary.
        :return: Tuple containing first and last names.
        :rtype: tuple[str, str]
        """
        truncate_text = _Utils.truncate_text
        full_name = truncate_text(customer_data.get("name"), 255)
        first_name = truncate_text(customer_data.get("first_name"), 255)
        last_name = truncate_text(customer_data.get("last_name"), 255)
        if full_name and not (first_name or last_name):
            return _Utils.split_customer_name(full_name)
        return first_name, last_name

    @staticmethod
    def shopping_cart_summary(shopping_cart_data, limit=255):
        """Build a short human-readable cart summary for order descriptions.

        :param dict shopping_cart_data: Cart payload dictionary.
        :param int limit: Max description field limit.
        :return: Short text describing cart lines or None.
        :rtype: str or None
        """
        if not isinstance(shopping_cart_data, dict):
            return None

        items_data = shopping_cart_data.get("items")
        if not isinstance(items_data, list):
            return None

        summary_parts = []
        for item_data in items_data:
            if not isinstance(item_data, dict):
                continue

            item_name = _Utils.truncate_text(item_data.get("name"), 80)
            if not item_name:
                continue

            quantity = _Utils.format_cart_quantity(item_data.get("quantity"))
            summary_parts.append(f"{quantity}x {item_name}")

        if not summary_parts:
            return None

        return _Utils.truncate_text(
            ", ".join(summary_parts),
            limit,
        )

    @staticmethod
    def order_description(data, remote_order_id, shopping_cart_summary):
        """Build the terminal-visible Cloud POS order description.

        :param dict data: Checkout payload parameters.
        :param str remote_order_id: Unique order ID reference.
        :param str shopping_cart_summary: Cart description text (ignored).
        :return: Trimmed description string.
        :rtype: str
        """
        return _Utils.truncate_text(
            data.get("description") or remote_order_id,
            255,
        )

    @staticmethod
    def checkout_options(payment_method, shopping_cart):
        """Build checkout options and tax tables for cart validation.

        :param pos.payment.method payment_method: The associated payment method.
        :param multisafepay.api.shared.cart.shopping_cart.ShoppingCart shopping_cart: SDK ShoppingCart.
        :return: CheckoutOptions SDK object or None.
        :rtype: multisafepay.api.paths.orders.request.components.checkout_options.CheckoutOptions or None
        """
        if not shopping_cart or not shopping_cart.items:
            return None

        tax_rules = []
        seen_selectors = set()
        for cart_item in shopping_cart.items:
            selector = getattr(cart_item, "tax_table_selector", None)
            if selector is None:
                continue

            selector = str(selector)
            if selector in seen_selectors:
                continue

            try:
                tax_rate = Decimal(selector)
            except (InvalidOperation, TypeError, ValueError):
                continue

            tax_rules.append(
                TaxRule(
                    name=selector,
                    standalone=True,
                    rules=[TaxRate(rate=float(tax_rate))],
                )
            )
            seen_selectors.add(selector)

        options = CheckoutOptionsRequest(
            tax_tables=CheckoutOptionsTaxTables(
                default=DefaultTaxRate(rate=0.0, shipping_taxed=True),
                alternate=tax_rules,
            ),
        )
        options.add_validate_cart(bool(payment_method.msp_cloud_validate_cart))
        return options
