# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details


class _Status:
    """Normalize Cloud POS statuses and collapse them into POS states.

    This class manages the mapping between external MultiSafepay status strings
    and internal Odoo POS states. By isolating the state-machine logic here,
    we follow the Single Responsibility Principle and ensure that status interpretation
    is consistent and centrally managed.
    """

    STATUS_MAP = {
        "created": "initialized",
        "waiting": "pending",
        "authorised": "processing",
        "authorized": "processing",
        "cancelled": "canceled",
        "success": "paid",
        "reversed": "refunded",
    }
    SUCCESS_STATES = {"paid", "completed", "refunded", "partial_refunded"}
    FAILURE_STATES = {"failed", "declined", "expired", "canceled", "void", "error"}

    @classmethod
    def normalize(cls, status):
        """Map MultiSafepay status aliases to local Cloud POS statuses.

        :param str status: Raw status string from the API.
        :return: Normalized status string.
        :rtype: str
        """
        normalized = (status or "initialized").lower()
        return cls.STATUS_MAP.get(normalized, normalized)

    @classmethod
    def state(cls, status):
        """Collapse Cloud POS statuses into pending, success or failure states.

        :param str status: Raw status string from the API.
        :return: Consolidated state string ('success', 'failure', or 'pending').
        :rtype: str
        """
        normalized = cls.normalize(status)
        if normalized in cls.SUCCESS_STATES:
            return "success"
        if normalized in cls.FAILURE_STATES:
            return "failure"
        return "pending"
