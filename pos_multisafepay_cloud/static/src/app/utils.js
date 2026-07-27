/** @odoo-module */

// Copyright (c) MultiSafepay, Inc. All rights reserved.
// This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
// See the LICENSE.md file for more information.
// See the DISCLAIMER.md file for disclaimer details

/**
 * Utility functions formerly in CloudPOSSanitizer that are still used.
 */
export class Utils {
    /** Split a full customer name into first and last name components. */
    static splitCustomerName(name) {
        const parts = String(name || "")
            .trim()
            .split(/\s+/)
            .filter(Boolean);
        if (!parts.length) {
            return ["", ""];
        }
        if (parts.length === 1) {
            return [parts[0], ""];
        }
        return [parts[0], parts.slice(1).join(" ")];
    }

    /** Sanitize identifiers for API transmission. */
    static sanitizeOrderId(value) {
        const sanitized = String(value || "")
            .replace(/[^a-zA-Z0-9_-]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 80);
        return sanitized || "pos-order";
    }

    /** Determine the base order identifier for mapping retry sequences. */
    static buildAttemptBase(order) {
        return this.sanitizeOrderId(
            order.pos_reference || order.name || order.uuid || "pos-order"
        );
    }

    /** Format a unique execution identifier incorporating the retry sequence index. */
    static formatAttemptId(base, attemptNumber) {
        return attemptNumber ? `${base}-${attemptNumber}` : base;
    }
}
