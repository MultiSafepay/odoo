# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from decimal import Decimal

from odoo.addons.pos_multisafepay_cloud.helpers.utils import (
    _Utils,
)


class _OrderContextBuilder:
    """Build context metadata from POS shopping cart data.

    This class is dedicated to extracting shopping cart details and calculating payment
    metadata (like tip amounts and item counts) from POS initialization payloads.
    This extraction adheres to the Single Responsibility Principle by keeping
    calculation and mapping logic out of the main transaction flow.
    """

    @classmethod
    def from_payload(cls, data):
        """Extract shopping cart metadata and build Odoo payment contextual fields.

        :param dict data: The initialization data payload.
        :return: A dictionary of contextual payment fields (e.g. odoo_tip_amount).
        :rtype: dict
        """
        items = cls._extract_items(data)
        cart_amount, tip_amount, tip_line_count = cls._calculate_totals(items)

        return {
            "odoo_order_amount": data.get("amount") if isinstance(data, dict) else None,
            "odoo_shopping_cart_item_count": len(items),
            "odoo_shopping_cart_amount": float(cart_amount),
            "odoo_shopping_cart_amount_cents": _Utils.amount_to_minor_units(cart_amount),
            "odoo_tip_amount": float(tip_amount),
            "odoo_tip_amount_cents": _Utils.amount_to_minor_units(tip_amount),
            "odoo_tip_line_count": tip_line_count,
        }

    @staticmethod
    def _extract_items(data):
        """Safely extract shopping cart items from the payload.

        :param dict data: The initialization data payload.
        :return: A list of shopping cart item dictionaries.
        :rtype: list
        """
        if not isinstance(data, dict):
            return []
        shopping_cart = data.get("shopping_cart")
        if not isinstance(shopping_cart, dict):
            return []
        items = shopping_cart.get("items")
        return items if isinstance(items, list) else []

    @staticmethod
    def _calculate_totals(items):
        """Calculate the total cart amount and tip specifics from cart items.

        :param list items: The list of shopping cart items.
        :return: A tuple containing cart_amount, tip_amount, and tip_line_count.
        :rtype: tuple[Decimal, Decimal, int]
        """
        cart_amount = Decimal("0")
        tip_amount = Decimal("0")
        tip_line_count = 0

        for item in items:
            if not isinstance(item, dict):
                continue
            unit_price = _Utils.parse_decimal(item.get("unit_price"))
            quantity = _Utils.parse_decimal(item.get("quantity") or 0)
            item_amount = abs(unit_price * quantity)

            cart_amount += item_amount
            if item.get("msp_cloud_is_tip"):
                tip_amount += item_amount
                tip_line_count += 1

        return cart_amount, tip_amount, tip_line_count
