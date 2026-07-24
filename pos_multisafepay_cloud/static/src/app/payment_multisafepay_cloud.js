/** @odoo-module */

// Copyright (c) MultiSafepay, Inc. All rights reserved.
// This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
// See the LICENSE.md file for more information.
// See the DISCLAIMER.md file for disclaimer details

/**
 * MultiSafepay Cloud POS JavaScript Payment Interface Integration.
 *
 * This module extends Odoo's Point of Sale `PaymentInterface` to enable seamless payment
 * processing, cancellations, reversals, and refunds through MultiSafepay Cloud POS terminals.
 *
 * Overview of Key Modules and Workflow:
 * 1. Helper Utilities: Build customer profile, shopping cart items, tip amounts, and identify refundable lines.
 * 2. Payment Interface (`PaymentMultiSafepayCloud`):
 *    - Checkout Entry Point (`send_payment_request`): Prepares order payload and invokes backend RPC `multisafepay_cloud_rpc_payment_request`.
 *    - Status Polling (`_schedule_status_poll` & `handle_multisafepay_cloud_status_response`): Polls Odoo backend via `multisafepay_cloud_rpc_poll_payment_status` every 2s until terminal transaction reaches a final state.
 *    - Terminal Cancellation (`send_payment_cancel`): Asks cashier confirmation and invokes `multisafepay_cloud_rpc_cancel_payment_request`.
 *    - Payment Reversals (`send_payment_reversal`): Voids uncompleted transactions via `multisafepay_cloud_rpc_reverse_payment_request`.
 *    - Refund Requests (`_send_refund_request`): Issues full/partial refunds via `multisafepay_cloud_rpc_refund_payment_request`.
 */

import {_t} from "@web/core/l10n/translation";
import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import {register_payment_method} from "@point_of_sale/app/store/pos_store";
import {
    AlertDialog,
    ConfirmationDialog,
} from "@web/core/confirmation_dialog/confirmation_dialog";
import {Utils} from "@pos_multisafepay_cloud/app/utils";

/**
 * Extract and sanitize partner details from a POS order to build a MultiSafepay customer dictionary.
 *
 * @param {Object} order - The active POS order.
 * @returns {Object|null} Customer object containing billing/shipping address or null if no partner attached.
 */
export function buildCustomer(order) {
    // Retrieve partner object from POS order
    const partner =
        order?.partner_id || order?.getPartner?.() || order?.partner || null;
    if (!partner) {
        return null;
    }

    // Split full customer name into first and last names for MultiSafepay API compliance
    const partnerName = partner.name || partner.display_name || "";
    const [firstName, lastName] = Utils.splitCustomerName(partnerName);

    const customer = {
        name: partnerName,
        reference: Utils.sanitizeOrderId(partner.id || partner.barcode || partnerName),
        locale: partner.lang || "en_US",
        first_name: firstName,
        last_name: lastName,
        address1: partner.street || "",
        address2: partner.street2 || "",
        zip_code: partner.zip || "",
        city: partner.city || "",
        state: partner.state_id?.name || "",
        country: partner.country_id?.code || "",
        phone: partner.phone || partner.mobile || "",
        email: partner.email || "",
    };

    // Strip empty attributes to prevent API validation rejections
    return Object.fromEntries(
        Object.entries(customer).filter(
            ([, value]) => value !== null && value !== undefined && value !== ""
        )
    );
}

/**
 * Safely retrieve order lines array across different Odoo POS data structures.
 *
 * @param {Object} order - The active POS order.
 * @returns {Array} List of order line objects.
 */
export function getOrderLines(order) {
    return order?.get_orderlines?.() || order?.lines || [];
}

/**
 * Resolve the product record from a POS order line.
 *
 * @param {Object} line - Order line object.
 * @returns {Object|null} Product record object or null.
 */
export function getLineProduct(line) {
    return line.product_id || line.getProduct?.() || null;
}

/**
 * Check if a POS order line corresponds to a tip product.
 *
 * @param {Object} line - Order line object.
 * @param {Object} pos - The active POS store instance.
 * @returns {Boolean} True if line is a tip product.
 */
export function isTipLine(line, pos) {
    if (typeof line?.isTipLine === "function") {
        return line.isTipLine();
    }
    const tipProduct = pos?.config?.tip_product_id;
    const product = getLineProduct(line);
    return Boolean(tipProduct?.id && product?.id && product.id === tipProduct.id);
}

/**
 * Calculate total tip amount attached to a POS order.
 *
 * @param {Object} order - The active POS order.
 * @param {Object} pos - The active POS store instance.
 * @returns {Number|null} Tip amount value or null if tipping disabled.
 */
export function buildTipAmount(order, pos) {
    if (!pos?.config?.iface_tipproduct || !pos?.config?.tip_product_id) {
        return null;
    }
    if (order?.tip_amount !== undefined && order?.tip_amount !== null) {
        return order.tip_amount;
    }
    if (typeof order?.getTip === "function") {
        return order.getTip();
    }
    return 0;
}

/**
 * Build a structured MultiSafepay shopping cart payload from POS order lines.
 *
 * @param {Object} order - The active POS order.
 * @param {Object} pos - The active POS store instance.
 * @returns {Object|null} Cart payload containing items array or null if empty.
 */
export function buildShoppingCart(order, pos) {
    const orderLines = getOrderLines(order);
    if (!orderLines.length) {
        return null;
    }

    const items = orderLines.map((line) => {
        const product = getLineProduct(line);
        const productId = product?.id || null;
        const productName =
            product?.display_name || product?.name || product?.full_product_name;
        const taxes = product?.taxes_id || [];

        // Identify tip lines to tag line items appropriately
        const isTip = isTipLine(line, pos);
        const taxRate = taxes.length ? taxes[0].amount || 0 : 0;

        // Resolve unit price with fallbacks across Odoo versions
        const possiblePrices =
            [
                line.price_unit,
                line.price,
                line.price_subtotal,
                line.price_subtotal_incl,
                typeof line.get_unit_price === "function"
                    ? line.get_unit_price()
                    : undefined,
                typeof line.get_price_with_tax === "function"
                    ? line.get_price_with_tax()
                    : undefined,
                typeof line.get_price_without_tax === "function"
                    ? line.get_price_without_tax()
                    : undefined,
            ].find((p) => p !== undefined && p !== null && p !== 0) || 0;

        // Resolve line quantity
        const possibleQty =
            [
                line.qty,
                line.quantity,
                typeof line.get_quantity === "function"
                    ? line.get_quantity()
                    : undefined,
            ].find((q) => q !== undefined && q !== null) || 1;

        return {
            name: line.full_product_name || productName || "POS Item",
            description: "",
            unit_price: possiblePrices,
            quantity: possibleQty,
            merchant_item_id: String(productId || "pos-item"),
            tax_rate_percentage: taxRate,
            msp_cloud_is_tip: isTip,
        };
    });

    return {items};
}

/**
 * Check if a POS payment line is an eligible MultiSafepay Cloud payment that can be refunded.
 *
 * @param {Object} paymentLine - The payment line record.
 * @returns {Boolean} True if line is a valid MultiSafepay Cloud payment line.
 */
export function isRefundableMspCloudPaymentLine(paymentLine) {
    return Boolean(
        paymentLine &&
            paymentLine.amount > 0 &&
            !paymentLine.is_change &&
            paymentLine.payment_method_id?.use_payment_terminal ===
                "multisafepay_cloud" &&
            (paymentLine.transaction_id || paymentLine.id)
    );
}

/**
 * Filter and collect refundable MultiSafepay Cloud payment lines from original source orders.
 *
 * @param {Object} order - The active POS refund order.
 * @returns {Array} List of refundable payment line records.
 */
export function getRefundableMspCloudPaymentLines(order) {
    const sourceOrderLines = getOrderLines(order)
        .map((orderLine) => orderLine.refunded_orderline_id)
        .filter(Boolean);
    const paymentLinesByKey = new Map();
    for (const orderLine of sourceOrderLines) {
        for (const paymentLine of orderLine.order_id?.payment_ids || []) {
            if (!isRefundableMspCloudPaymentLine(paymentLine)) {
                continue;
            }
            paymentLinesByKey.set(paymentLine.id || paymentLine.uuid, paymentLine);
        }
    }
    return [...paymentLinesByKey.values()];
}

/**
 * Resolve the original MultiSafepay Cloud payment line associated with a refund payment line.
 *
 * @param {Object} order - The active POS order.
 * @param {Object} refundPaymentLine - The refund payment line.
 * @returns {Object|null} Matching original payment line or null.
 */
export function getRefundSourcePaymentLine(order, refundPaymentLine) {
    const refundablePaymentLines = getRefundableMspCloudPaymentLines(order);
    const refundedPaymentId = refundPaymentLine.refundedPaymentId;

    // Match explicitly selected payment line by ID/UUID
    if (refundedPaymentId) {
        return refundablePaymentLines.find(
            (line) =>
                String(line.id) === String(refundedPaymentId) ||
                String(line.uuid) === String(refundedPaymentId)
        );
    }
    // Auto-select if exactly 1 MultiSafepay payment exists on source order
    return refundablePaymentLines.length === 1 ? refundablePaymentLines[0] : null;
}

/**
 * Payment interface implementation for the MultiSafepay Cloud POS terminal.
 */
export class PaymentMultiSafepayCloud extends PaymentInterface {
    /**
     * Set up services, configuration, and internal mapping registries.
     */
    setup() {
        super.setup(...arguments);
        this.enable_reversals();
        this.dialog = this.env.services.dialog;
        this.orm = this.env.services.orm;
        this.paymentLineResolvers = {};
        this.paymentPollTimeouts = {};
    }

    /**
     * Define whether this terminal supports fast/offline payments.
     *
     * @returns {Boolean} Always false.
     */
    get fast_payments() {
        return false;
    }

    /**
     * Retrieve the active payment line by its UUID or the default selected line.
     *
     * @param {string|null} uuid - Optional unique payment line identifier.
     * @returns {Object|null} The payment line matching the UUID.
     */
    get_payment_line(uuid = null) {
        const order = this.pos.get_order();
        if (!order) {
            return null;
        }
        const targetUuid = uuid || this.pendingPaymentLineUuid;
        if (targetUuid && order.get_paymentline_by_uuid) {
            return order.get_paymentline_by_uuid(targetUuid);
        }
        return order.get_selected_paymentline();
    }

    /**
     * Initiate a payment or refund request for the given payment line UUID.
     *
     * Workflow:
     * - If amount < 0, delegates to `_send_refund_request`.
     * - Formats attempt ID and registers pending promise resolver.
     * - Assembles customer, cart, and tip payloads.
     * - Invokes backend RPC `multisafepay_cloud_rpc_payment_request`.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @returns {Promise<boolean>} Resolves to true if payment succeeded.
     */
    async send_payment_request(uuid) {
        await super.send_payment_request(...arguments);

        const order = this.pos.get_order();
        const line = order?.get_paymentline_by_uuid(uuid);
        if (!line) {
            return false;
        }

        // Intercept negative payment amounts to route through terminal refund workflow
        if (line.amount < 0) {
            return this._send_refund_request(order, line);
        }

        this.pendingPaymentLineUuid = uuid;

        // Construct unique payment attempt tracking IDs (e.g. ORDER-1) for retry safety
        const mspCloudAttemptBase =
            line.msp_cloud_attempt_base || Utils.buildAttemptBase(order);
        const mspCloudAttemptNumber = line.msp_cloud_attempt_number || 0;
        const mspCloudUid = Utils.formatAttemptId(
            mspCloudAttemptBase,
            mspCloudAttemptNumber
        );

        // Direct in-memory assignment for instant reactivity in _is_current_pending_payment
        line.msp_cloud_attempt_base = mspCloudAttemptBase;
        line.msp_cloud_attempt_number = mspCloudAttemptNumber + 1;
        line.msp_cloud_uid = mspCloudUid;
        try {
            line.update({
                msp_cloud_attempt_base: mspCloudAttemptBase,
                msp_cloud_attempt_number: mspCloudAttemptNumber + 1,
                msp_cloud_uid: mspCloudUid,
            });
        } catch {
            // Fallback if database schema does not persist custom tracking fields
        }

        // Register pending Promise resolver; POS UI pauses until terminal completes or cancels
        const paymentConfirmation = this._register_pending_payment(uuid, mspCloudUid);
        const customer = buildCustomer(order);
        const shoppingCart = buildShoppingCart(order, this.pos);
        const tipAmount = buildTipAmount(order, this.pos);
        const data = {
            msp_cloud_uid: mspCloudUid,
            msp_cloud_attempt_base: mspCloudAttemptBase,
            msp_cloud_attempt_number: mspCloudAttemptNumber,
            description: _t("Order #") + order.pos_reference,
            pos_reference: order.pos_reference,
            order_id: order.uuid,
            currency: this.pos.currency.name,
            amount: line.amount,
            tip_amount: tipAmount,
            customer,
            shopping_cart: shoppingCart,
            session_id:
                this.pos.pos_session?.id ||
                window.odoo?.pos_session_id ||
                this.pos.session?.id,
            payment_method_id: this.payment_method_id.id,
        };

        // Send RPC to backend pos.payment.method and handle initial terminal response
        this._submit_payment(data, uuid, mspCloudUid)
            .then((response) =>
                this._handle_initial_response(line, response, mspCloudUid)
            )
            .catch(() => {
                this._handle_odoo_connection_failure(uuid, mspCloudUid);
            });
        return paymentConfirmation;
    }

    /**
     * Cancel a pending payment transaction on the terminal screen.
     *
     * Workflow:
     * - Prompts cashier confirmation dialog ("Force Cancel").
     * - Invokes backend RPC `multisafepay_cloud_rpc_cancel_payment_request`.
     * - Resolves checkout promise to false and resets line status to 'retry'.
     *
     * @param {Object} order - The active POS order.
     * @param {String} uuid - Unique payment line identifier.
     * @returns {Promise<boolean>} Resolves to true if cancel request succeeded.
     */
    async send_payment_cancel(order, uuid) {
        return new Promise((resolve) => {
            const line = order?.get_paymentline_by_uuid(uuid);

            // Ask cashier confirmation before canceling terminal prompt
            this.dialog.add(ConfirmationDialog, {
                title: _t("Cancel MultiSafepay Payment"),
                body: _t(
                    "Cancel this payment attempt on the terminal? If the terminal is unresponsive, click Force Cancel to unlock Odoo POS."
                ),
                confirmLabel: _t("Force Cancel"),
                confirm: async () => {
                    const line = order?.get_paymentline_by_uuid(uuid);

                    // Invoke RPC cancellation on pos.multisafepay.cloud.payment
                    const response = await this.orm.silent
                        .call(
                            "pos.multisafepay.cloud.payment",
                            "multisafepay_cloud_rpc_cancel_payment_request",
                            [],
                            {
                                order_id: line?.transaction_id,
                                msp_cloud_uid: line?.msp_cloud_uid,
                                payment_method_id: this.payment_method_id.id,
                            }
                        )
                        .catch(() => null);

                    if (!response) {
                        this._show_error(
                            _t("Could not connect to Odoo to cancel the payment."),
                            _t("Connection Error")
                        );
                        resolve(false);
                        return true;
                    }

                    // Validate response status to ensure cancellation was acknowledged
                    const state = (response.state || "").toLowerCase();
                    const status = (response.status || "").toLowerCase();
                    if (
                        state !== "success" &&
                        !["canceled", "expired", "failed", "declined", "void"].includes(
                            status
                        )
                    ) {
                        this._show_error(
                            response.detail ||
                                _t("MultiSafepay Cloud POS cancellation failed."),
                            _t("MultiSafepay Cloud")
                        );
                        resolve(false);
                        return true;
                    }

                    // Unlock POS UI and mark payment line as retryable
                    super.send_payment_cancel(...arguments);
                    this._resolve_pending_payment(uuid, false, line?.msp_cloud_uid);
                    if (this.pendingPaymentLineUuid === uuid) {
                        this.pendingPaymentLineUuid = null;
                    }
                    if (line) {
                        line.set_payment_status("retry");
                    }
                    this.pos.paymentTerminalInProgress = false;
                    resolve(true);
                    return true;
                },
                cancelLabel: _t("Discard"),
                cancel: () => resolve(false),
            });
        });
    }

    /**
     * Trigger a transaction reversal (void/cancellation) on the terminal for an incomplete payment.
     *
     * Invokes backend RPC `multisafepay_cloud_rpc_reverse_payment_request`.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @returns {Promise<boolean>} Resolves to true if reversal succeeded.
     */
    async send_payment_reversal(uuid) {
        const line = this.get_payment_line(uuid);
        if (!line) {
            return false;
        }

        // Send reversal request to backend model pos.multisafepay.cloud.payment
        const response = await this.orm.silent
            .call(
                "pos.multisafepay.cloud.payment",
                "multisafepay_cloud_rpc_reverse_payment_request",
                [],
                {
                    order_id: line.transaction_id,
                    msp_cloud_uid: line.msp_cloud_uid,
                    amount: line.amount,
                    currency: this.pos.currency.name,
                }
            )
            .catch(() => {
                this._show_error(
                    _t(
                        "Could not connect to Odoo to reverse the payment. Check your connection and try again."
                    ),
                    _t("Connection Error")
                );
                return null;
            });

        if (!response) {
            return false;
        }

        // Check if transaction was successfully voided or refunded
        const state = (response.state || "").toLowerCase();
        const status = (response.status || "").toLowerCase();
        if (
            state === "success" ||
            ["refunded", "partial_refunded", "canceled", "cancelled", "void"].includes(
                status
            )
        ) {
            line.update({
                transaction_id:
                    response.order_id || response.transaction_id || line.transaction_id,
            });
            return true;
        }

        this._show_error(
            response.detail || _t("MultiSafepay Cloud POS reversal failed."),
            _t("MultiSafepay Cloud")
        );
        return false;
    }

    /**
     * Send a refund request to MultiSafepay Cloud for a specific payment line.
     *
     * Workflow:
     * - Identifies original source payment line via `getRefundSourcePaymentLine`.
     * - Invokes backend RPC `multisafepay_cloud_rpc_refund_payment_request`.
     * - Updates payment line with refund transaction ID and reference.
     *
     * @param {Object} order - The active POS order.
     * @param {Object} line - The payment line to refund.
     * @returns {Promise<boolean>} True if refund was successfully initiated.
     */
    async _send_refund_request(order, line) {
        // Locate original completed payment line to link refund request
        const sourcePaymentLine = getRefundSourcePaymentLine(order, line);
        if (!sourcePaymentLine) {
            this._show_error(
                _t("Select the original MultiSafepay Cloud POS payment to refund."),
                _t("MultiSafepay Cloud")
            );
            return false;
        }

        line.set_payment_status("waitingCard");
        // Execute refund RPC call via pos.multisafepay.cloud.payment
        const response = await this.orm.silent
            .call(
                "pos.multisafepay.cloud.payment",
                "multisafepay_cloud_rpc_refund_payment_request",
                [],
                {
                    refunded_payment_id: sourcePaymentLine.id || sourcePaymentLine.uuid,
                    order_id: sourcePaymentLine.transaction_id,
                    msp_cloud_uid: sourcePaymentLine.msp_cloud_uid,
                    amount: line.amount,
                    currency: this.pos.currency.name,
                }
            )
            .catch(() => {
                this._show_error(
                    _t(
                        "Could not connect to Odoo to refund the payment. Check your connection and try again."
                    ),
                    _t("Connection Error")
                );
                return null;
            });

        if (!response) {
            return false;
        }

        // Record refund ID and reference on payment line upon success
        const state = (response.state || "").toLowerCase();
        const status = (response.status || "").toLowerCase();
        if (state === "success" || ["refunded", "partial_refunded"].includes(status)) {
            line.update({
                transaction_id:
                    response.refund_id ||
                    response.transaction_id ||
                    line.transaction_id,
                payment_ref_no: response.order_id || sourcePaymentLine.transaction_id,
                msp_cloud_refund_source_order_id:
                    response.order_id || sourcePaymentLine.transaction_id,
            });
            return true;
        }

        this._show_error(
            response.detail || _t("MultiSafepay Cloud POS refund failed."),
            _t("MultiSafepay Cloud")
        );
        return false;
    }

    /**
     * Submit a payment request payload to the Odoo backend controller.
     * Invokes RPC `multisafepay_cloud_rpc_payment_request` on `pos.payment.method`.
     *
     * @param {Object} data - Payload data including amount, currency, and cart.
     * @param {string|null} uuid - Optional unique payment line identifier.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     * @returns {Promise} The ORM call promise.
     */
    _submit_payment(data, uuid = null, mspCloudUid = null) {
        return this.orm.silent
            .call("pos.payment.method", "multisafepay_cloud_rpc_payment_request", [
                [this.payment_method_id.id],
                data,
            ])
            .catch(() => this._handle_odoo_connection_failure(uuid, mspCloudUid));
    }

    /**
     * Handle connection errors when communicating with the Odoo server.
     *
     * @param {string|null} uuid - Optional unique payment line identifier.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     * @returns {null} Always returns null.
     */
    _handle_odoo_connection_failure(uuid = null, mspCloudUid = null) {
        const line = this.get_payment_line(uuid);
        if (mspCloudUid && line?.msp_cloud_uid !== mspCloudUid) {
            return null;
        }
        if (line) {
            line.set_payment_status("retry");
        }
        const paymentUuid = uuid || line?.uuid || this.pendingPaymentLineUuid;
        if (paymentUuid) {
            this._resolve_pending_payment(paymentUuid, false, mspCloudUid);
        }
        this.pos.paymentTerminalInProgress = false;
        this._show_error(
            _t("Could not connect to Odoo. Check your connection and try again."),
            _t("Connection Error")
        );
        return null;
    }

    /**
     * Process the initial response from Odoo after sending a payment request.
     *
     * Workflow:
     * - If state is 'success', resolves payment immediately.
     * - If state is 'pending' or empty, starts status polling timer (`_schedule_status_poll`).
     * - If failed, resets payment line status to 'retry'.
     *
     * @param {Object} line - The active payment line record.
     * @param {Object} response - The response payload.
     * @param {String} mspCloudUid - Unique payment execution identifier.
     * @returns {Boolean} True if payment completed immediately.
     */
    _handle_initial_response(line, response, mspCloudUid) {
        // Ignore response if cashier navigated away or changed attempt
        if (!this._is_current_pending_payment(line, mspCloudUid)) {
            return false;
        }

        if (
            !["waiting", "waitingCard", "waitingCancel"].includes(line.payment_status)
        ) {
            line.set_payment_status("retry");
            this._resolve_pending_payment(line.uuid, false, mspCloudUid);
            return false;
        }

        if (!response) {
            line.set_payment_status("retry");
            this._resolve_pending_payment(line.uuid, false, mspCloudUid);
            return false;
        }

        const state = (response?.state || "").toLowerCase();
        const remoteOrderId = response?.order_id || response?.id;
        if (remoteOrderId) {
            this._update_pending_payment_attempt_id(
                line.uuid,
                mspCloudUid,
                remoteOrderId
            );
            mspCloudUid = remoteOrderId;
            line.msp_cloud_uid = remoteOrderId;
        }
        line.update({
            transaction_id: remoteOrderId || line.transaction_id,
            msp_cloud_uid: remoteOrderId || line.msp_cloud_uid,
        });

        // Fast-path resolution if terminal completed payment instantly
        if (state === "success") {
            this._show_msp_cloud_warning(response);
            this._resolve_pending_payment(line.uuid, true, mspCloudUid);
            return true;
        }

        // Standard Cloud POS flow: transaction is pending on terminal, start polling loop
        if (!state || state === "pending") {
            if (line.payment_status !== "waitingCancel") {
                line.set_payment_status("waitingCard");
            }
            this._schedule_status_poll(line.uuid, mspCloudUid);
            return true;
        }

        // Terminal initialization failed; unlock line for retry
        this._show_error(
            response?.detail || _t("MultiSafepay Cloud payment request failed.")
        );
        line.set_payment_status("retry");
        this._resolve_pending_payment(line.uuid, false, mspCloudUid);
        return false;
    }

    /**
     * Map a unique identifier to a promise resolver representing the pending checkout.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @param {String} mspCloudUid - Unique payment execution identifier.
     * @returns {Promise} The transaction outcome promise.
     */
    _register_pending_payment(uuid, mspCloudUid) {
        this._clear_poll_timeout(uuid);
        return new Promise((resolve) => {
            this.paymentLineResolvers[uuid] = {mspCloudUid, resolve};
        });
    }

    /**
     * Schedule a polling task to check transaction status at short intervals (every 2000ms).
     * Invokes `handle_multisafepay_cloud_status_response` on each interval.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @param {String} mspCloudUid - Unique payment execution identifier.
     */
    _schedule_status_poll(uuid, mspCloudUid) {
        this._clear_poll_timeout(uuid);
        this.paymentPollTimeouts[uuid] = setTimeout(async () => {
            const line = this.get_payment_line(uuid);
            // Stop polling loop if payment line state was canceled or resolved elsewhere
            if (
                !this._is_current_pending_payment(line, mspCloudUid) ||
                !["waiting", "waitingCard", "waitingCancel"].includes(
                    line.payment_status
                )
            ) {
                return;
            }

            // Poll Odoo backend for updated webhook/API status
            await this.handle_multisafepay_cloud_status_response(uuid, mspCloudUid);

            // Recursively schedule next poll tick if payment remains in pending state
            const refreshedLine = this.get_payment_line(uuid);
            if (
                this._is_current_pending_payment(refreshedLine, mspCloudUid) &&
                ["waiting", "waitingCard", "waitingCancel"].includes(
                    refreshedLine.payment_status
                )
            ) {
                this._schedule_status_poll(uuid, mspCloudUid);
            }
        }, 2000);
    }

    /**
     * Clear the polling timeout registered for a specific payment line.
     *
     * @param {String} uuid - Unique payment line identifier.
     */
    _clear_poll_timeout(uuid) {
        if (this.paymentPollTimeouts[uuid]) {
            clearTimeout(this.paymentPollTimeouts[uuid]);
            delete this.paymentPollTimeouts[uuid];
        }
    }

    /**
     * Retrieve the transaction status from Odoo database via RPC `multisafepay_cloud_rpc_poll_payment_status`.
     * If the backend reports 'success' or 'failure', updates line and resolves checkout.
     *
     * @param {string|null} uuid - Optional unique payment line identifier.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     */
    async handle_multisafepay_cloud_status_response(uuid = null, mspCloudUid = null) {
        const line = this.get_payment_line(uuid);
        if (!this._is_current_pending_payment(line, mspCloudUid)) {
            return;
        }

        // Poll backend ORM pos.multisafepay.cloud.payment for latest webhook/API status
        const paymentStatus = await this.orm.call(
            "pos.multisafepay.cloud.payment",
            "multisafepay_cloud_rpc_poll_payment_status",
            [],
            {
                order_id: line.transaction_id,
                msp_cloud_uid: line.msp_cloud_uid,
            }
        );

        if (!paymentStatus || !this._is_current_pending_payment(line, mspCloudUid)) {
            return;
        }

        line.update({
            transaction_id:
                paymentStatus.order_id ||
                paymentStatus.transaction_id ||
                line.transaction_id,
        });

        // Terminal completed successfully; resolve checkout Promise with success=true
        const state = (paymentStatus.state || "").toLowerCase();
        if (state === "success") {
            this._show_msp_cloud_warning(paymentStatus);
            this._resolve_payment_status(line.uuid, true, mspCloudUid);
            return;
        }

        // Terminal transaction failed/declined; resolve checkout Promise with success=false
        if (state === "failure") {
            if (paymentStatus.detail) {
                this._show_error(paymentStatus.detail, _t("MultiSafepay Cloud"));
            }
            this._resolve_payment_status(line.uuid, false, mspCloudUid);
        }
    }

    /**
     * Resolve the status of a payment line and update Odoo's payment state.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @param {Boolean} success - True if the payment was completed successfully.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     */
    _resolve_payment_status(uuid, success, mspCloudUid = null) {
        const resolvedPendingPayment = this._resolve_pending_payment(
            uuid,
            success,
            mspCloudUid
        );
        if (resolvedPendingPayment) {
            return;
        }

        const line = this.get_payment_line(uuid);
        if (!line || (mspCloudUid && line.msp_cloud_uid !== mspCloudUid)) {
            return;
        }

        line.handle_payment_response(success);
    }

    /**
     * Resolve the checkout promise mapper for a pending payment attempt.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @param {Boolean} success - True if transaction completed successfully.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     * @returns {Boolean} True if a pending registry was found and resolved.
     */
    _resolve_pending_payment(uuid, success, mspCloudUid = null) {
        const pendingPayment = this.paymentLineResolvers[uuid];
        if (
            !pendingPayment ||
            (mspCloudUid && pendingPayment.mspCloudUid !== mspCloudUid)
        ) {
            return false;
        }

        // Clean up polling timer and resolver map to prevent memory leaks
        this._clear_poll_timeout(uuid);
        delete this.paymentLineResolvers[uuid];
        if (this.pendingPaymentLineUuid === uuid) {
            this.pendingPaymentLineUuid = null;
        }

        // Unblock POS UI by resolving the pending checkout Promise
        pendingPayment.resolve(success);
        return true;
    }

    /**
     * Update the tracked transaction reference code of a pending payment resolver.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @param {String} currentMspCloudUid - Existing identifier key.
     * @param {String} nextMspCloudUid - New identifier key to assign.
     */
    _update_pending_payment_attempt_id(uuid, currentMspCloudUid, nextMspCloudUid) {
        const pendingPayment = this.paymentLineResolvers[uuid];
        if (pendingPayment?.mspCloudUid === currentMspCloudUid) {
            pendingPayment.mspCloudUid = nextMspCloudUid;
        }
    }

    /**
     * Verify if the active checkout execution matches a given tracking key.
     *
     * @param {Object} line - The active payment line record.
     * @param {string|null} mspCloudUid - Unique execution identifier to check.
     * @returns {Boolean} True if matched.
     */
    _is_current_pending_payment(line, mspCloudUid = null) {
        if (!line) {
            return false;
        }
        const pendingPayment = this.paymentLineResolvers[line.uuid];
        // Safety check matching line UUID and msp_cloud_uid tracking token
        return Boolean(
            pendingPayment &&
                (!mspCloudUid || pendingPayment.mspCloudUid === mspCloudUid) &&
                line.msp_cloud_uid === pendingPayment.mspCloudUid
        );
    }

    /**
     * Display an alert popup dialog to the user with a localized message.
     *
     * @param {String} message - The message content.
     * @param {String} title - The dialog header title.
     */
    _show_error(message, title = _t("MultiSafepay Cloud Error")) {
        this.dialog.add(AlertDialog, {
            title,
            body: message,
        });
    }

    /**
     * Display a warning pop-up if the server response contains a warning annotation.
     *
     * @param {Object} response - The API response object.
     */
    _show_msp_cloud_warning(response) {
        if (response?.warning) {
            this._show_error(response.warning, _t("MultiSafepay Cloud"));
        }
    }
}

register_payment_method("multisafepay_cloud", PaymentMultiSafepayCloud);
