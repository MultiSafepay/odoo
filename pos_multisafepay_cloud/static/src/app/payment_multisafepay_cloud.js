/** @odoo-module */

// Copyright (c) MultiSafepay, Inc. All rights reserved.
// This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
// See the LICENSE.md file for more information.
// See the DISCLAIMER.md file for disclaimer details

import {_t} from "@web/core/l10n/translation";
import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import {register_payment_method} from "@point_of_sale/app/store/pos_store";
import {
    AlertDialog,
    ConfirmationDialog,
} from "@web/core/confirmation_dialog/confirmation_dialog";
import {Utils} from "@pos_multisafepay_cloud/app/utils";

export function buildCustomer(order) {
    const partner =
        order?.partner_id || order?.getPartner?.() || order?.partner || null;
    if (!partner) {
        return null;
    }
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
    return Object.fromEntries(
        Object.entries(customer).filter(
            ([, value]) => value !== null && value !== undefined && value !== ""
        )
    );
}

export function getOrderLines(order) {
    return order?.get_orderlines?.() || order?.lines || [];
}

export function buildShoppingCart(order, pos) {
    const orderLines = getOrderLines(order);
    if (!orderLines.length) {
        return null;
    }

    const tipProductId =
        pos?.config?.tip_product_id?.[0] ||
        pos?.config?.tip_product_id?.id ||
        pos?.config?.tip_product_id;

    const items = orderLines.map((line) => {
        const product = line.product_id || line.product || line.get_product?.();
        let productId = null;
        let productName = null;
        let taxes = [];

        if (Array.isArray(product)) {
            productId = product[0];
            productName = product[1];
        } else if (product && typeof product === "object") {
            productId = product.id;
            productName =
                product.display_name || product.name || product.full_product_name;
            taxes = product.taxes_id || [];
        }

        const isTip = Boolean(
            tipProductId && productId && String(productId) === String(tipProductId)
        );
        const taxRate = taxes.length ? taxes[0].amount || 0 : 0;

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

export function getRefundSourcePaymentLine(order, refundPaymentLine) {
    const refundablePaymentLines = getRefundableMspCloudPaymentLines(order);
    const refundedPaymentId = refundPaymentLine.refundedPaymentId;
    if (refundedPaymentId) {
        return refundablePaymentLines.find(
            (line) =>
                String(line.id) === String(refundedPaymentId) ||
                String(line.uuid) === String(refundedPaymentId)
        );
    }
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

        if (line.amount < 0) {
            return this._send_refund_request(order, line);
        }

        this.pendingPaymentLineUuid = uuid;
        const mspCloudAttemptBase =
            line.msp_cloud_attempt_base || Utils.buildAttemptBase(order);
        const mspCloudAttemptNumber = line.msp_cloud_attempt_number || 0;
        const mspCloudUid = Utils.formatAttemptId(
            mspCloudAttemptBase,
            mspCloudAttemptNumber
        );

        // Set directly for immediate in-memory access (critical for _is_current_pending_payment).
        // Also call update() to persist reactively if the field exists in the DB schema.
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
            // Field may not be in DB schema yet; direct assignment above is the fallback.
        }

        const paymentConfirmation = this._register_pending_payment(uuid, mspCloudUid);
        const customer = buildCustomer(order);
        const shoppingCart = buildShoppingCart(order, this.pos);
        const data = {
            msp_cloud_uid: mspCloudUid,
            msp_cloud_attempt_base: mspCloudAttemptBase,
            msp_cloud_attempt_number: mspCloudAttemptNumber,
            description: _t("Order #") + order.pos_reference,
            pos_reference: order.pos_reference,
            order_id: order.uuid,
            currency: this.pos.currency.name,
            amount: line.amount,
            customer,
            shopping_cart: shoppingCart,
            session_id:
                this.pos.pos_session?.id ||
                window.odoo?.pos_session_id ||
                this.pos.session?.id,
            payment_method_id: this.payment_method_id.id,
        };

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
     * @param {Object} order - The active POS order.
     * @param {String} uuid - Unique payment line identifier.
     * @returns {Promise<boolean>} Resolves to true if cancel request succeeded.
     */
    async send_payment_cancel(order, uuid) {
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: _t("Cancel MultiSafepay Cloud payment"),
                body: _t(
                    "This will cancel the active MultiSafepay Cloud POS payment on the terminal."
                ),
                confirmLabel: _t("Force Cancel"),
                confirm: async () => {
                    const line = order?.get_paymentline_by_uuid(uuid);

                    const response = await this.orm.silent
                        .call(
                            "pos.multisafepay.cloud.payment",
                            "cancel_payment_request",
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
     * Trigger a transaction reversal (void/cancellation) on the terminal.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @returns {Promise<boolean>} Resolves to true if reversal succeeded.
     */
    async send_payment_reversal(uuid) {
        const line = this.get_payment_line(uuid);
        if (!line) {
            return false;
        }

        const response = await this.orm.silent
            .call("pos.multisafepay.cloud.payment", "reverse_payment_request", [], {
                order_id: line.transaction_id,
                msp_cloud_uid: line.msp_cloud_uid,
                amount: line.amount,
                currency: this.pos.currency.name,
            })
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
     * @param {Object} order - The active POS order.
     * @param {Object} line - The payment line to refund.
     * @returns {Promise<boolean>} True if refund was successfully initiated.
     */
    async _send_refund_request(order, line) {
        const sourcePaymentLine = getRefundSourcePaymentLine(order, line);
        if (!sourcePaymentLine) {
            this._show_error(
                _t("Select the original MultiSafepay Cloud POS payment to refund."),
                _t("MultiSafepay Cloud")
            );
            return false;
        }

        line.set_payment_status("waitingCard");
        const response = await this.orm.silent
            .call("pos.multisafepay.cloud.payment", "refund_payment_request", [], {
                refunded_payment_id: sourcePaymentLine.id || sourcePaymentLine.uuid,
                order_id: sourcePaymentLine.transaction_id,
                msp_cloud_uid: sourcePaymentLine.msp_cloud_uid,
                amount: line.amount,
                currency: this.pos.currency.name,
            })
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
     *
     * @param {Object} data - Payload data including amount, currency, and cart.
     * @param {string|null} uuid - Optional unique payment line identifier.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     * @returns {Promise} The ORM call promise.
     */
    _submit_payment(data, uuid = null, mspCloudUid = null) {
        return this.orm.silent
            .call("pos.payment.method", "multisafepay_cloud_payment_request", [
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
     * @param {Object} line - The active payment line record.
     * @param {Object} response - The response payload.
     * @param {String} mspCloudUid - Unique payment execution identifier.
     * @returns {Boolean} True if payment completed immediately.
     */
    _handle_initial_response(line, response, mspCloudUid) {
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

        if (state === "success") {
            this._show_msp_cloud_warning(response);
            this._resolve_pending_payment(line.uuid, true, mspCloudUid);
            return true;
        }

        if (!state || state === "pending") {
            if (line.payment_status !== "waitingCancel") {
                line.set_payment_status("waitingCard");
            }
            this._schedule_status_poll(line.uuid, mspCloudUid);
            return true;
        }

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
     * Schedule a polling task to check transaction status at short intervals.
     *
     * @param {String} uuid - Unique payment line identifier.
     * @param {String} mspCloudUid - Unique payment execution identifier.
     */
    _schedule_status_poll(uuid, mspCloudUid) {
        this._clear_poll_timeout(uuid);
        this.paymentPollTimeouts[uuid] = setTimeout(async () => {
            const line = this.get_payment_line(uuid);
            if (
                !this._is_current_pending_payment(line, mspCloudUid) ||
                !["waiting", "waitingCard", "waitingCancel"].includes(
                    line.payment_status
                )
            ) {
                return;
            }

            await this.handle_multisafepay_cloud_status_response(uuid, mspCloudUid);

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
     * Retrieve the transaction status from Odoo and trigger UI resolution if finalized.
     *
     * @param {string|null} uuid - Optional unique payment line identifier.
     * @param {string|null} mspCloudUid - Optional unique payment execution identifier.
     */
    async handle_multisafepay_cloud_status_response(uuid = null, mspCloudUid = null) {
        const line = this.get_payment_line(uuid);
        if (!this._is_current_pending_payment(line, mspCloudUid)) {
            return;
        }

        const paymentStatus = await this.orm.call(
            "pos.multisafepay.cloud.payment",
            "poll_payment_status",
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

        const state = (paymentStatus.state || "").toLowerCase();
        if (state === "success") {
            this._show_msp_cloud_warning(paymentStatus);
            this._resolve_payment_status(line.uuid, true, mspCloudUid);
            return;
        }

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

        this._clear_poll_timeout(uuid);
        delete this.paymentLineResolvers[uuid];
        if (this.pendingPaymentLineUuid === uuid) {
            this.pendingPaymentLineUuid = null;
        }

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
