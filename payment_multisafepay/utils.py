# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import base64
import logging
from functools import lru_cache

import requests

_logger = logging.getLogger(__name__)
DEFAULT_REQUEST_TIMEOUT = 10  # seconds


def _get_image_base64(url):
    try:
        _logger.debug("URL %s", url)
        # Reuse shared session (with default timeout) to avoid creating new connections.
        response = _get_requests_session().get(url)
        if response.status_code == 200:
            return base64.b64encode(response.content)
    except Exception as e:
        _logger.warning("Could not fetch image from %s: %s", url, e)
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
