# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from functools import lru_cache
from multisafepay.transport import RequestsTransport

DEFAULT_CLOUD_POS_TIMEOUT_SECONDS = 60


class _Transport(RequestsTransport):
    """Requests transport that applies a default timeout when none is provided.

    This class extends the base SDK transport mechanism to ensure that all HTTP
    requests have a safety timeout. Extracting network-level configurations into
    this transport class strictly adheres to the Single Responsibility Principle,
    preventing the SDK usage code from managing low-level request behaviors.
    """

    def __init__(self):
        """Initialize requests transport with default timeout settings."""
        self.default_timeout = DEFAULT_CLOUD_POS_TIMEOUT_SECONDS
        super().__init__()

    def _with_default_timeout(self, kwargs):
        """Add the default timeout to the request arguments if not already present.

        :param dict kwargs: The keyword arguments of the request.
        :return: Updated request keyword arguments dictionary.
        :rtype: dict
        """
        kwargs.setdefault("timeout", self.default_timeout)
        return kwargs

    def request(self, method, url, headers=None, data=None, **kwargs):
        """Execute a requests transport network call with default timeout values.

        :param str method: The HTTP method (e.g. GET, POST).
        :param str url: Target request URL.
        :param dict headers: Request HTTP headers.
        :param data: Request body data.
        :param dict kwargs: Additional keyword arguments.
        :return: SDK HTTP response object.
        """
        kwargs = self._with_default_timeout(kwargs)
        return super().request(method, url, headers, data, **kwargs)

    def open_stream(self, method, url, headers=None, data=None, **kwargs):
        """Open a requests transport stream with default timeout values.

        :param str method: The HTTP method (e.g. GET, POST).
        :param str url: Target request URL.
        :param dict headers: Request HTTP headers.
        :param data: Request body data.
        :param dict kwargs: Additional keyword arguments.
        :return: Stream SDK context manager.
        """
        kwargs = self._with_default_timeout(kwargs)
        return super().open_stream(method, url, headers, data, **kwargs)


@lru_cache(maxsize=8)
def _get_cloud_pos_transport():
    """Return a cached requests transport with a default request timeout."""
    return _Transport()
