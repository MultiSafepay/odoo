# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import logging

from multisafepay.util.webhook import Webhook

_logger = logging.getLogger(__name__)


class _NotificationValidator:
    """Validate notification signatures using Webhook utilities.

    This class isolates the security concern of verifying incoming webhook signatures.
    By extracting the validation logic into its own class, we adhere to the Single
    Responsibility Principle, ensuring that security checks can be tested, modified,
    or reused independently of the webhook endpoint's business logic.
    """

    @classmethod
    def validate(cls, payment_name, payment_method, raw_body=None, auth_header=None):
        """Validate signature from a MultiSafepay notification webhook request.

        :param str payment_name: The tracking reference/order name.
        :param pos.payment.method payment_method: The associated payment method.
        :param bytes/str raw_body: The raw request body of the webhook.
        :param str auth_header: The Auth header containing signature data.
        :return: True if signature is valid or auth parameters are absent, False otherwise.
        :rtype: bool
        """
        if not raw_body or not auth_header:
            return True

        api_keys = cls._get_api_keys(payment_method)
        if not api_keys:
            _logger.warning(
                "MSP Cloud POS notification for order %s has an Auth header, but no API key is configured to validate it.",
                payment_name,
            )
            return False

        return cls._validate_with_api_keys(
            payment_name, raw_body, auth_header, api_keys
        )

    @staticmethod
    def _get_api_keys(payment_method):
        """Extract configured API keys from the payment method."""
        api_keys = []
        for api_key in (
            payment_method.msp_cloud_terminal_group_api_key,
            payment_method.msp_cloud_account_api_key,
        ):
            api_key = (api_key or "").strip()
            if api_key and api_key not in api_keys:
                api_keys.append(api_key)
        return api_keys

    @staticmethod
    def _validate_with_api_keys(payment_name, raw_body, auth_header, api_keys):
        """Attempt validation against a list of API keys."""
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
                payment_name,
                len(api_keys),
                validation_error,
            )
        return False
