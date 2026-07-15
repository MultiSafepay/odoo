# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import re
from decimal import Decimal, InvalidOperation


class _Utils:
    """Format and sanitize POS payload values for Cloud POS API requests.

    This class provides static utilities for cleaning, truncating, and converting basic
    data types (like decimals and strings) before they are sent to the API.
    Isolating data formatting utilities into this class follows the Single Responsibility
    Principle and prevents repetitive sanitation logic across the codebase.
    """

    @staticmethod
    def parse_decimal(value):
        """Parse Cloud POS payload amount values defensively as Decimal.

        :param value: Float, string, or decimal value to parse.
        :return: Decoded Decimal representation.
        :rtype: Decimal
        """
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    @classmethod
    def amount_to_minor_units(cls, amount, currency):
        """Convert a major-unit amount to MultiSafepay minor units.

        :param float/Decimal/str amount: The amount value in major units.
        :param res.currency currency: Odoo currency used for rounding and precision.
        :return: Value converted to integer minor units.
        :rtype: int
        """
        if not currency:
            raise ValueError("Currency is required to determine decimal precision.")
        decimal_places = getattr(currency, "decimal_places", None)
        if decimal_places is None:
            raise ValueError("Currency decimal_places is not defined.")

        amount_decimal = cls.parse_decimal(amount)
        rounded_amount = cls.parse_decimal(currency.round(float(amount_decimal)))
        return int(rounded_amount.scaleb(int(decimal_places)))

    @staticmethod
    def sanitize_order_id(value, fallback):
        """Return an API-safe order id based on an arbitrary value.

        :param str/int value: The value to sanitize.
        :param str fallback: The fallback value to use if sanitization results in an empty string.
        :return: API-safe sanitized string.
        :rtype: str
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "")).strip("-")[:80]
        return sanitized or str(fallback)

    @staticmethod
    def split_customer_name(name):
        """Split a full customer name into first and last name components.

        :param str name: The customer's full name.
        :return: A tuple of first_name and last_name.
        :rtype: tuple[str, str]
        """
        name_parts = str(name or "").strip().split()
        if not name_parts:
            return "", ""
        if len(name_parts) == 1:
            return name_parts[0], name_parts[0]
        return name_parts[0], " ".join(name_parts[1:])

    @staticmethod
    def format_cart_quantity(quantity):
        """Format POS cart quantities without unnecessary decimal noise.

        :param float/int/str quantity: Cart line item quantity.
        :return: Normalized string representation of the quantity.
        :rtype: str
        """
        try:
            quantity_decimal = Decimal(str(quantity or 0))
        except (InvalidOperation, TypeError, ValueError):
            quantity_decimal = Decimal("0")

        quantity_decimal = abs(quantity_decimal.normalize())
        if quantity_decimal == quantity_decimal.to_integral_value():
            return str(int(quantity_decimal))
        return format(quantity_decimal, "f")

    @staticmethod
    def truncate_text(value, limit):
        """Normalize whitespace and truncate text to the API field limit.

        :param str value: The text value to process.
        :param int limit: Character limit for truncation.
        :return: Trimmed and potentially truncated string with ellipsis.
        :rtype: str
        """
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return text[: max(limit - 3, 0)].rstrip() + "..."

    @classmethod
    def format_country_code(cls, country):
        """Return a valid two-letter uppercase country code or blank.

        :param str country: Country name or code to evaluate.
        :return: Valid ISO code or blank string.
        :rtype: str
        """
        country = cls.truncate_text(country, 2).upper()
        return country if len(country) == 2 else ""

    @classmethod
    def format_email(cls, email):
        """Return a trimmed email value only when it resembles an email address.

        :param str email: Email address string to clean.
        :return: Sanitized email string or empty string.
        :rtype: str
        """
        email = cls.truncate_text(email, 255)
        return email if email and "@" in email else ""

    @staticmethod
    def tax_rate_from_percentage(tax_rate_percentage):
        """Convert a percentage tax rate to the API decimal tax rate format.

        :param float/Decimal/str tax_rate_percentage: Tax rate percent (e.g. 21.0).
        :return: Decimal tax rate representation (e.g. 0.21).
        :rtype: Decimal
        """
        try:
            percentage = Decimal(str(tax_rate_percentage or 0))
        except (InvalidOperation, TypeError, ValueError):
            percentage = Decimal("0")
        if percentage < 0:
            percentage = Decimal("0")
        return (percentage / Decimal("100")).quantize(Decimal("0.000001")).normalize()
