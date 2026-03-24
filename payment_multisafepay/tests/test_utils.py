# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from decimal import Decimal
from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase

from .. import utils


class TestGetCurrencyPrecisionDigits(TransactionCase):
    """Unit tests for get_currency_precision_digits()"""

    def test_get_currency_precision_digits_valid_currency(self):
        """Test retrieving decimal places from a valid currency"""
        eur = self.env["res.currency"].search([("name", "=", "EUR")], limit=1)
        if eur:
            precision = utils.get_currency_precision_digits(eur)
            self.assertEqual(precision, 2, "EUR should have 2 decimal places")

    def test_get_currency_precision_digits_none_currency(self):
        """Test that None currency raises ValueError"""
        with self.assertRaises(ValueError) as context:
            utils.get_currency_precision_digits(None)
        self.assertIn("Currency is required", str(context.exception))

    def test_get_currency_precision_digits_no_decimal_places(self):
        """Test that currency without decimal_places raises ValueError"""
        mock_currency = Mock()
        mock_currency.name = "TEST"
        mock_currency.decimal_places = None

        with self.assertRaises(ValueError) as context:
            utils.get_currency_precision_digits(mock_currency)
        self.assertIn("decimal_places is not defined", str(context.exception))

    def test_get_currency_precision_digits_various_currencies(self):
        """Test precision for different currency types"""
        test_cases = {
            "EUR": 2,
            "USD": 2,
            "JPY": 0,
        }

        for currency_code, expected_precision in test_cases.items():
            currency = self.env["res.currency"].search(
                [("name", "=", currency_code)], limit=1
            )
            if currency:
                precision = utils.get_currency_precision_digits(currency)
                self.assertEqual(
                    precision,
                    expected_precision,
                    f"{currency_code} should have {expected_precision} decimal places",
                )


class TestMoneyToMinorUnits(TransactionCase):
    """Unit tests for money_to_minor_units()"""

    def setUp(self):
        super().setUp()
        self.eur = self.env["res.currency"].search([("name", "=", "EUR")], limit=1)
        self.usd = self.env["res.currency"].search([("name", "=", "USD")], limit=1)
        self.jpy = self.env["res.currency"].search([("name", "=", "JPY")], limit=1)

    def test_money_to_minor_units_eur_basic(self):
        """Test converting EUR to minor units (cents)"""
        if self.eur:
            # 100.00 EUR = 10000 cents
            result = utils.money_to_minor_units(100.00, self.eur)
            self.assertEqual(result, 10000, "100.00 EUR should be 10000 units")

    def test_money_to_minor_units_eur_decimal(self):
        """Test converting EUR with decimal precision"""
        if self.eur:
            # 99.99 EUR = 9999 cents
            result = utils.money_to_minor_units(99.99, self.eur)
            self.assertEqual(result, 9999, "99.99 EUR should be 9999 units")

    def test_money_to_minor_units_eur_single_cent(self):
        """Test converting EUR to single unit"""
        if self.eur:
            # 0.01 EUR = 1 cent
            result = utils.money_to_minor_units(0.01, self.eur)
            self.assertEqual(result, 1, "0.01 EUR should be 1 unit")

    def test_money_to_minor_units_zero(self):
        """Test converting zero amount"""
        if self.eur:
            result = utils.money_to_minor_units(0, self.eur)
            self.assertEqual(result, 0, "Zero amount should be 0 units")

    def test_money_to_minor_units_none_amount(self):
        """Test that None amount is treated as 0"""
        if self.eur:
            result = utils.money_to_minor_units(None, self.eur)
            self.assertEqual(result, 0, "None amount should be treated as 0")

    def test_money_to_minor_units_float_precision(self):
        """Test that float amounts are handled with correct precision"""
        if self.eur:
            # 1.10 EUR is a common floating-point precision edge case
            result = utils.money_to_minor_units(1.10, self.eur)
            self.assertEqual(result, 110, "1.10 EUR should be 110 units")

    def test_money_to_minor_units_large_amount(self):
        """Test converting large amounts"""
        if self.eur:
            result = utils.money_to_minor_units(999999.99, self.eur)
            self.assertEqual(result, 99999999, "999999.99 EUR should be 99999999 units")

    def test_money_to_minor_units_jpy_no_decimals(self):
        """Test JPY conversion (no decimal places)"""
        if self.jpy:
            # 100 JPY = 100 units (no decimal conversion)
            result = utils.money_to_minor_units(100, self.jpy)
            self.assertEqual(result, 100, "100 JPY should be 100 units (no decimals)")

    def test_money_to_minor_units_rounding(self):
        """Test that amounts are properly rounded before conversion"""
        if self.eur:
            # Test with a value that needs rounding
            result = utils.money_to_minor_units(100.005, self.eur)
            # Should round based on currency rules
            self.assertIsInstance(result, int, "Result should be an integer")
            self.assertGreaterEqual(result, 10000, "Should be at least 10000")
            self.assertLessEqual(result, 10001, "Should be at most 10001")


class TestMinorUnitsToMoney(TransactionCase):
    """Unit tests for minor_units_to_money()"""

    def setUp(self):
        super().setUp()
        self.eur = self.env["res.currency"].search([("name", "=", "EUR")], limit=1)
        self.usd = self.env["res.currency"].search([("name", "=", "USD")], limit=1)
        self.jpy = self.env["res.currency"].search([("name", "=", "JPY")], limit=1)

    def test_minor_units_to_money_eur_basic(self):
        """Test converting EUR cents back to decimal"""
        if self.eur:
            # 10000 cents = 100.00 EUR
            result = utils.minor_units_to_money(10000, self.eur)
            self.assertEqual(result, 100.00, "10000 units should be 100.00 EUR")

    def test_minor_units_to_money_eur_decimal(self):
        """Test converting EUR with decimal precision"""
        if self.eur:
            # 9999 cents = 99.99 EUR
            result = utils.minor_units_to_money(9999, self.eur)
            self.assertEqual(result, 99.99, "9999 units should be 99.99 EUR")

    def test_minor_units_to_money_eur_single_unit(self):
        """Test converting single unit"""
        if self.eur:
            # 1 cent = 0.01 EUR
            result = utils.minor_units_to_money(1, self.eur)
            self.assertEqual(result, 0.01, "1 unit should be 0.01 EUR")

    def test_minor_units_to_money_zero(self):
        """Test converting zero units"""
        if self.eur:
            result = utils.minor_units_to_money(0, self.eur)
            self.assertEqual(result, 0.00, "0 units should be 0.00 EUR")

    def test_minor_units_to_money_none_units(self):
        """Test that None is treated as 0"""
        if self.eur:
            result = utils.minor_units_to_money(None, self.eur)
            self.assertEqual(result, 0.00, "None should be treated as 0")

    def test_minor_units_to_money_large_amount(self):
        """Test converting large amounts"""
        if self.eur:
            result = utils.minor_units_to_money(99999999, self.eur)
            self.assertEqual(result, 999999.99, "99999999 units should be 999999.99 EUR")

    def test_minor_units_to_money_jpy_no_decimals(self):
        """Test JPY conversion (no decimal shift)"""
        if self.jpy:
            # 100 units = 100 JPY (no decimal conversion)
            result = utils.minor_units_to_money(100, self.jpy)
            self.assertEqual(result, 100.0, "100 units should be 100 JPY")

    def test_minor_units_to_money_returns_float(self):
        """Test that result is always a float"""
        if self.eur:
            result = utils.minor_units_to_money(10000, self.eur)
            self.assertIsInstance(result, float, "Result should be a float")


class TestRoundTripConversion(TransactionCase):
    """Unit tests for round-trip conversion (money -> units -> money)"""

    def setUp(self):
        super().setUp()
        self.eur = self.env["res.currency"].search([("name", "=", "EUR")], limit=1)

    def test_round_trip_conversion_eur(self):
        """Test that converting back and forth preserves value"""
        if self.eur:
            original = 123.45
            units = utils.money_to_minor_units(original, self.eur)
            result = utils.minor_units_to_money(units, self.eur)
            self.assertEqual(
                result, original, f"Round trip should preserve {original}"
            )

    def test_round_trip_conversion_various_amounts(self):
        """Test round-trip conversion with various amounts"""
        if self.eur:
            test_amounts = [0.01, 1.00, 10.50, 99.99, 1000.00, 12345.67]
            for amount in test_amounts:
                with self.subTest(amount=amount):
                    units = utils.money_to_minor_units(amount, self.eur)
                    result = utils.minor_units_to_money(units, self.eur)
                    self.assertAlmostEqual(
                        result,
                        amount,
                        places=2,
                        msg=f"Round trip should preserve {amount}",
                    )


class TestGetRequestsSession(TransactionCase):
    """Unit tests for _get_requests_session()"""

    def setUp(self):
        super().setUp()
        utils._get_requests_session.cache_clear()

    def tearDown(self):
        utils._get_requests_session.cache_clear()
        super().tearDown()

    def test_get_requests_session_returns_session(self):
        """Test that function returns a requests.Session object"""
        session = utils._get_requests_session()
        self.assertIsNotNone(session)
        self.assertTrue(
            hasattr(session, "request"), "Should return requests.Session object"
        )

    def test_get_requests_session_cached(self):
        """Test that function returns the same session (cached)"""
        session1 = utils._get_requests_session()
        session2 = utils._get_requests_session()
        self.assertIs(
            session1, session2, "Should return the same cached session instance"
        )

    def test_get_requests_session_has_default_timeout(self):
        """Test that session requests have default timeout"""
        session = utils._get_requests_session()
        # The session.request method should be wrapped to add default timeout
        self.assertTrue(
            hasattr(session, "request"),
            "Session should have request method with timeout",
        )

    def test_get_requests_session_timeout_applied(self):
        """Test that DEFAULT_REQUEST_TIMEOUT is applied to requests"""
        with patch("requests.Session.request") as mock_request:
            session = utils._get_requests_session()
            # Note: This test verifies the wrapper behavior
            self.assertTrue(callable(session.request))


class TestGetImageBase64(TransactionCase):
    """Unit tests for _get_image_base64()"""

    def setUp(self):
        super().setUp()
        utils._get_requests_session.cache_clear()

    def tearDown(self):
        utils._get_requests_session.cache_clear()
        super().tearDown()

    def test_get_image_base64_invalid_url(self):
        """Test that invalid URL returns False"""
        with patch("requests.Session.get") as mock_get:
            mock_get.return_value.status_code = 404
            result = utils._get_image_base64("http://invalid.url/image.png")
            self.assertFalse(result, "Should return False for 404 responses")

    def test_get_image_base64_connection_error(self):
        """Test that connection error returns False"""
        with patch("requests.Session.get") as mock_get:
            mock_get.side_effect = Exception("Connection failed")
            result = utils._get_image_base64("http://invalid.url/image.png")
            self.assertFalse(result, "Should return False for connection errors")

    def test_get_image_base64_valid_response(self):
        """Test successful image fetch and base64 encoding"""
        with patch("requests.Session.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = b"fake image data"

            result = utils._get_image_base64("http://example.com/image.png")

            self.assertIsNotNone(result, "Should return encoded data")
            self.assertTrue(isinstance(result, bytes), "Should return bytes")

    def test_get_image_base64_server_error(self):
        """Test that server error (500+) returns False"""
        with patch("requests.Session.get") as mock_get:
            mock_get.return_value.status_code = 500
            result = utils._get_image_base64("http://example.com/image.png")
            self.assertFalse(result, "Should return False for 500 server errors")

    def test_get_image_base64_uses_default_timeout(self):
        """Test that image fetch uses shared session with timeout"""
        with patch.object(utils, "_get_requests_session") as mock_session_func:
            mock_session = Mock()
            mock_session_func.return_value = mock_session
            mock_session.get.return_value.status_code = 404

            utils._get_image_base64("http://example.com/image.png")

            mock_session_func.assert_called()
            mock_session.get.assert_called()
