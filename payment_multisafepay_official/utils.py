# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging
from decimal import Decimal
from functools import lru_cache

import requests

from odoo.tools import BinaryBytes, file_open

_logger = logging.getLogger(__name__)
DEFAULT_REQUEST_TIMEOUT = 10  # seconds


def _get_image_binary(url):
    # migracion_19_20: Binary/Image fields reject base64 bytes in Odoo 20; return a BinaryBytes value.
    try:
        _logger.debug("URL %s", url)
        # Reuse shared session (with default timeout) to avoid creating new connections.
        response = _get_requests_session().get(url)
        if response.status_code == 200:
            return BinaryBytes(response.content)
    except Exception as e:
        _logger.warning(f"Could not fetch image from {url}: {e}")
    return False


def _get_default_payment_method_image():
    # migracion_19_20: payment.method.image is required in Odoo 20, so methods without an API icon use the module icon.
    with file_open(
        "payment_multisafepay_official/static/description/icon.png", "rb"
    ) as icon_file:
        return BinaryBytes(icon_file.read())


@lru_cache(maxsize=1)
def _get_requests_session():
    """Return the shared requests session used by MultiSafepay SDK transports."""

    session = requests.Session()
    original_request = session.request

    def request_with_default_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", DEFAULT_REQUEST_TIMEOUT)
        return original_request(method, url, **kwargs)

    session.request = request_with_default_timeout
    return session


def get_currency_precision_digits(currency):
    """Return decimal precision for currency from Odoo configuration."""
    if not currency:
        raise ValueError("Currency is required to determine decimal precision.")

    decimal_places = getattr(currency, "decimal_places", None)
    if decimal_places is None:
        raise ValueError(
            "Currency decimal_places is not defined on Odoo currency "
            f"'{getattr(currency, 'name', 'unknown')}'."
        )

    return int(decimal_places)


def money_to_minor_units(money, currency):
    """Convert an amount in currency units to gateway units (integer)."""
    decimal_places = get_currency_precision_digits(currency)
    rounded_amount = currency.round(money or 0)
    amount_decimal = Decimal(str(rounded_amount))
    return int(amount_decimal.scaleb(decimal_places))


def minor_units_to_money(minor_units, currency):
    """Convert an amount in gateway units (integer) to currency units."""
    decimal_places = get_currency_precision_digits(currency)
    amount_decimal = Decimal(str(minor_units or 0)).scaleb(-decimal_places)
    return currency.round(float(amount_decimal))
