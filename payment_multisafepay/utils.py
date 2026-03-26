# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import base64
import logging
from decimal import Decimal
from functools import lru_cache

import requests

_logger = logging.getLogger(__name__)
DEFAULT_REQUEST_TIMEOUT = 10  # seconds


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


def minor_units_to_money(amount_units, currency):
    """Convert gateway units (integer) to amount in currency units."""
    decimal_places = get_currency_precision_digits(currency)
    amount_units_decimal = Decimal(str(amount_units or 0))
    return float(amount_units_decimal.scaleb(-decimal_places))


def _get_image_base64(url):
    try:
        _logger.debug("URL %s", url)
        # Reuse shared session (with default timeout) to avoid creating new connections.
        response = _get_requests_session().get(url)
        if response.status_code == 200:
            return base64.b64encode(response.content)
    except Exception as e:
        _logger.warning(f"Could not fetch image from {url}: {e}")
    return False


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
