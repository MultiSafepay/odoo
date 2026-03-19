# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

import time

import psycopg2

from odoo.http import request


def is_serialization_conflict(error):
    """Return True when the DB error corresponds to a serialization conflict."""
    return getattr(error, "pgcode", None) == "40001" or (
        "could not serialize access due to concurrent update" in str(error).lower()
    )


def process_notification_with_retry(
    payment_transaction,
    notification_data,
    new_status,
    transactionid,
    duplicated_status_checker,
    logger,
    max_attempts=2,
    retry_delays=None,
):
    """Process notification data with limited retry on serialization conflicts."""
    retry_delays = retry_delays or [0.05]

    for attempt in range(max_attempts):
        try:
            payment_transaction._process_notification_data(notification_data)

            logger.info(
                "Webhook processing completed for transaction %s with status %s",
                transactionid,
                new_status,
            )
            return request.make_response("OK", status=200)

        except psycopg2.OperationalError as concurrency_error:
            if not is_serialization_conflict(concurrency_error):
                raise

            request.env.cr.rollback()
            payment_transaction.invalidate_recordset(
                [
                    "state",
                    "state_message",
                    "last_state_change",
                    "is_post_processed",
                ]
            )
            if duplicated_status_checker(payment_transaction, new_status):
                logger.info(
                    "Serialization conflict for transaction %s resolved "
                    "idempotently (status already applied).",
                    transactionid,
                )
                return request.make_response("OK", status=200)

            if attempt == max_attempts - 1:
                logger.warning(
                    "Serialization conflict persisted for transaction %s "
                    "after %s attempts.",
                    transactionid,
                    max_attempts,
                )
                return request.make_response("Concurrency conflict", status=503)

            retry_delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            logger.warning(
                "Serialization conflict while processing transaction %s. "
                "Retrying in %.2fs (attempt %s/%s).",
                transactionid,
                retry_delay,
                attempt + 2,
                max_attempts,
            )
            time.sleep(retry_delay)
