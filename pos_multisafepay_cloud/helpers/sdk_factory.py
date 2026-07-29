# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import os
from urllib.parse import urlparse

from multisafepay import Sdk
from multisafepay.client import ScopedCredentialResolver

from .transport import (
    _get_cloud_pos_transport,
)


class _SDKFactory:
    """Build MultiSafepay SDK clients for Cloud POS payment methods.

    This class encapsulates the configuration and instantiation of the MultiSafepay
    SDK client. By extracting this into a factory, we adhere to the Single
    Responsibility Principle, allowing the core payment logic to simply request an
    SDK instance without worrying about environment configurations or API keys.
    """

    @classmethod
    def build(cls, terminal_group_id, terminal_group_api_key, custom_api_url):
        """Build an SDK client scoped to the configured terminal group.

        :param str terminal_group_id: Terminal group ID code.
        :param str terminal_group_api_key: Key assigned to the terminal group.
        :param str custom_api_url: Custom API URL for testing.
        :return: Instantiated SDK client.
        :rtype: multisafepay.Sdk
        """
        terminal_group_id = (terminal_group_id or "").strip()
        terminal_group_api_key = (terminal_group_api_key or "").strip()

        terminal_group_api_keys = (
            {terminal_group_id: terminal_group_api_key}
            if terminal_group_id and terminal_group_api_key
            else None
        )
        credential_resolver = ScopedCredentialResolver(
            default_api_key=terminal_group_api_key,
            terminal_group_api_keys=terminal_group_api_keys,
        )

        sdk_kwargs = {
            "is_production": True,
            "credential_resolver": credential_resolver,
            "transport": _get_cloud_pos_transport(),
        }

        custom_url = cls.normalize_custom_api_url((custom_api_url or "").strip())
        if custom_url:
            cls.enable_custom_base_url_override(custom_url)
            sdk_kwargs["base_url"] = custom_url

        return Sdk(**sdk_kwargs)

    @staticmethod
    def enable_custom_base_url_override(custom_url):
        """Enable SDK development flags required for a custom API base URL.

        :param str custom_url: The verified override base URL.
        """
        os.environ["MSP_SDK_BUILD_PROFILE"] = "dev"
        os.environ["MSP_SDK_ALLOW_CUSTOM_BASE_URL"] = "1"
        os.environ["MSP_SDK_CUSTOM_BASE_URL"] = custom_url

    @staticmethod
    def normalize_custom_api_url(base_url):
        """Validate and normalize a custom Cloud POS API base URL.

        :param str base_url: Override base URL string.
        :return: Normalized URL string.
        :rtype: str
        """
        if not base_url:
            return ""

        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid custom API URL.")

        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError("Invalid custom API URL.")

        path = parsed.path.rstrip("/")
        path = "/" if not path else f"{path}/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
