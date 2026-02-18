# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import base64
import logging

import requests

_logger = logging.getLogger(__name__)


def _get_image_base64(url):
    try:
        _logger.debug("URL %s", url)
        # Add timeout to external request
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return base64.b64encode(response.content)
    except Exception as e:
        _logger.warning("Could not fetch image from %s: %s", url, e)
    return False
