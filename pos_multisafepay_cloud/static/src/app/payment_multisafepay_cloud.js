/** @odoo-module */

import {_t} from "@web/core/l10n/translation";
import {PaymentInterface} from "@point_of_sale/app/payment/payment_interface";
import {register_payment_method} from "@point_of_sale/app/store/pos_store";
import {
    AlertDialog,
    ConfirmationDialog,
} from "@web/core/confirmation_dialog/confirmation_dialog";

export class PaymentMultiSafepayCloud extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.enable_reversals();
        this.dialog = this.env.services.dialog;
        this.orm = this.env.services.orm;
        this.paymentLineResolvers = {};
        this.paymentPollTimeouts = {};
    }

    get fast_payments() {
        return false;
    }

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
            line.msp_cloud_attempt_base || this._build_msp_cloud_attempt_base(order);
        const mspCloudAttemptNumber = line.msp_cloud_attempt_number || 0;
        const mspCloudUid = this._format_msp_cloud_attempt_id(
            mspCloudAttemptBase,
            mspCloudAttemptNumber
        );

        line.msp_cloud_attempt_base = mspCloudAttemptBase;
        line.msp_cloud_attempt_number = mspCloudAttemptNumber + 1;
        line.msp_cloud_uid = mspCloudUid;

        const paymentConfirmation = this._register_pending_payment(uuid, mspCloudUid);
        const customer = this._build_msp_cloud_customer(order);
        const shoppingCart = this._build_msp_cloud_shopping_cart(order);
        const data = {
            msp_cloud_uid: mspCloudUid,
            msp_cloud_attempt_base: mspCloudAttemptBase,
            msp_cloud_attempt_number: mspCloudAttemptNumber,
            description: _t("Order %s", order.pos_reference),
            pos_reference: order.pos_reference,
            order_id: order.uuid,
            currency: this.pos.currency.name,
            amount: line.amount,
            customer,
            shopping_cart: shoppingCart,
            session_id: this.pos.session.id,
            payment_method_id: this.payment_method_id.id,
        };

        this._submit_payment(data, uuid, mspCloudUid).then((response) =>
            this._handle_initial_response(line, response, mspCloudUid)
        );
        return paymentConfirmation;
    }

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
                    const isCancelSuccessful = await this._cancel_payment_request(line);
                    if (!isCancelSuccessful) {
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
            line.transaction_id =
                response.order_id || response.transaction_id || line.transaction_id;
            return true;
        }

        this._show_error(
            response.detail || _t("MultiSafepay Cloud POS reversal failed."),
            _t("MultiSafepay Cloud")
        );
        return false;
    }

    async _send_refund_request(order, line) {
        const sourcePaymentLine = this._get_refund_source_payment_line(order, line);
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
                refunded_payment_id: this._get_msp_cloud_record_id(sourcePaymentLine),
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
            line.transaction_id =
                response.refund_id || response.transaction_id || line.transaction_id;
            line.payment_ref_no = response.order_id || sourcePaymentLine.transaction_id;
            line.msp_cloud_refund_source_order_id =
                response.order_id || sourcePaymentLine.transaction_id;
            return true;
        }

        this._show_error(
            response.detail || _t("MultiSafepay Cloud POS refund failed."),
            _t("MultiSafepay Cloud")
        );
        return false;
    }

    _get_refund_source_payment_line(order, refundPaymentLine) {
        const refundablePaymentLines = this._get_refundable_msp_cloud_payment_lines(order);
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

    _get_refundable_msp_cloud_payment_lines(order) {
        const sourceOrderLines = (order?.getOrderlines?.() || order?.lines || [])
            .map((orderLine) => orderLine.refunded_orderline_id)
            .filter(Boolean);
        const paymentLinesByKey = new Map();
        for (const orderLine of sourceOrderLines) {
            for (const paymentLine of orderLine.order_id?.payment_ids || []) {
                if (!this._is_refundable_msp_cloud_payment_line(paymentLine)) {
                    continue;
                }
                paymentLinesByKey.set(paymentLine.id || paymentLine.uuid, paymentLine);
            }
        }
        return [...paymentLinesByKey.values()];
    }

    _is_refundable_msp_cloud_payment_line(paymentLine) {
        return Boolean(
            paymentLine &&
                paymentLine.amount > 0 &&
                !paymentLine.is_change &&
                paymentLine.payment_method_id?.use_payment_terminal === "multisafepay_cloud" &&
                (paymentLine.transaction_id || paymentLine.id)
        );
    }

    async _cancel_payment_request(line) {
        if (!line) {
            return false;
        }

        const response = await this.orm.silent
            .call("pos.multisafepay.cloud.payment", "cancel_payment_request", [], {
                order_id: line.transaction_id,
                msp_cloud_uid: line.msp_cloud_uid,
                payment_method_id: this.payment_method_id.id,
            })
            .catch(() => {
                this._show_error(
                    _t(
                        "Could not connect to Odoo to cancel the payment. Check your connection and try again."
                    ),
                    _t("Connection Error")
                );
                return null;
            });

        if (!response) {
            return false;
        }

        const status = (response.status || "").toLowerCase();
        if (
            ["canceled", "cancelled", "void", "expired", "failed", "declined"].includes(
                status
            )
        ) {
            return true;
        }

        this._show_error(
            response.detail || _t("MultiSafepay Cloud POS cancellation failed."),
            _t("MultiSafepay Cloud")
        );
        return false;
    }

    _submit_payment(data, uuid = null, mspCloudUid = null) {
        console.log("[MSP Cloud POS] RPC data", JSON.parse(JSON.stringify(data)));
        return this.orm.silent
            .call("pos.payment.method", "multisafepay_cloud_payment_request", [
                [this.payment_method_id.id],
                data,
            ])
            .catch(() => this._handle_odoo_connection_failure(uuid, mspCloudUid));
    }

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
        }
        line.transaction_id = remoteOrderId || line.transaction_id;
        line.msp_cloud_uid = remoteOrderId || line.msp_cloud_uid;

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

    _register_pending_payment(uuid, mspCloudUid) {
        this._clear_poll_timeout(uuid);
        return new Promise((resolve) => {
            this.paymentLineResolvers[uuid] = {mspCloudUid, resolve};
        });
    }

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
        }, 3000);
    }

    _clear_poll_timeout(uuid) {
        if (this.paymentPollTimeouts[uuid]) {
            clearTimeout(this.paymentPollTimeouts[uuid]);
            delete this.paymentPollTimeouts[uuid];
        }
    }

    async handle_multisafepay_cloud_status_response(uuid = null, mspCloudUid = null) {
        const line = this.get_payment_line(uuid);
        if (!this._is_current_pending_payment(line, mspCloudUid)) {
            return;
        }

        const paymentStatus = await this.orm.silent
            .call("pos.multisafepay.cloud.payment", "get_payment_status", [], {
                order_id: line.transaction_id,
                msp_cloud_uid: line.msp_cloud_uid,
            })
            .catch(() => this._handle_odoo_connection_failure(uuid, mspCloudUid));

        if (!paymentStatus || !this._is_current_pending_payment(line, mspCloudUid)) {
            return;
        }

        line.transaction_id =
            paymentStatus.order_id ||
            paymentStatus.transaction_id ||
            line.transaction_id;

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

    _update_pending_payment_attempt_id(uuid, currentMspCloudUid, nextMspCloudUid) {
        const pendingPayment = this.paymentLineResolvers[uuid];
        if (pendingPayment?.mspCloudUid === currentMspCloudUid) {
            pendingPayment.mspCloudUid = nextMspCloudUid;
        }
    }

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

    _show_error(message, title = _t("MultiSafepay Cloud Error")) {
        this.dialog.add(AlertDialog, {
            title,
            body: message,
        });
    }

    _show_msp_cloud_warning(response) {
        if (response?.warning) {
            this._show_error(response.warning, _t("MultiSafepay Cloud"));
        }
    }

    _build_msp_cloud_attempt_base(order) {
        return this._sanitize_msp_cloud_order_id(
            order.pos_reference || order.name || order.uuid || "pos-order"
        );
    }

    _format_msp_cloud_attempt_id(base, attemptNumber) {
        return attemptNumber ? `${base}-${attemptNumber}` : base;
    }

    _build_msp_cloud_shopping_cart(order) {
        const orderLines = order?.getOrderlines?.() || order?.lines || [];
        const items = orderLines
            .map((orderLine, index) =>
                this._build_msp_cloud_cart_item(orderLine, index)
            )
            .filter(Boolean);
        return items.length ? {items} : null;
    }

    _build_msp_cloud_customer(order) {
        const partner = this._get_msp_cloud_order_partner(order);
        if (!partner) {
            return null;
        }

        const partnerName = this._get_msp_cloud_record_name(partner);
        const [firstName, lastName] = this._split_msp_cloud_customer_name(partnerName);
        const customer = {
            name: partnerName,
            reference: this._sanitize_msp_cloud_order_id(
                this._get_msp_cloud_record_id(partner) || partner.barcode || partnerName
            ),
            locale: partner.lang || "en_US",
            first_name: firstName,
            last_name: lastName,
            address1: partner.street || "",
            address2: partner.street2 || "",
            zip_code: partner.zip || "",
            city: partner.city || "",
            state: this._get_msp_cloud_relation_name(partner.state_id),
            country: this._get_msp_cloud_country_code(partner.country_id),
            phone: partner.phone || partner.mobile || "",
            email: partner.email || "",
        };

        return Object.fromEntries(
            Object.entries(customer).filter(
                ([, value]) => value !== null && value !== undefined && value !== ""
            )
        );
    }

    _get_msp_cloud_order_partner(order) {
        return order?.partner_id || order?.getPartner?.() || order?.partner || null;
    }

    _get_msp_cloud_record_id(record) {
        if (!record) {
            return "";
        }
        if (Array.isArray(record)) {
            return record[0] || "";
        }
        if (typeof record === "number" || typeof record === "string") {
            return record;
        }
        return record.id || "";
    }

    _get_msp_cloud_record_name(record) {
        if (!record) {
            return "";
        }
        if (Array.isArray(record)) {
            return record[1] || "";
        }
        if (typeof record === "string") {
            return record;
        }
        return record.name || record.display_name || "";
    }

    _split_msp_cloud_customer_name(name) {
        const parts = String(name || "")
            .trim()
            .split(/\s+/)
            .filter(Boolean);
        if (!parts.length) {
            return ["", ""];
        }
        if (parts.length === 1) {
            return [parts[0], parts[0]];
        }
        return [parts[0], parts.slice(1).join(" ")];
    }

    _get_msp_cloud_relation_name(relation) {
        if (!relation) {
            return "";
        }
        if (Array.isArray(relation)) {
            const state = this.pos.models?.["res.country.state"]?.get?.(relation[0]);
            return state?.name || relation[1] || "";
        }
        if (typeof relation === "number") {
            return this.pos.models?.["res.country.state"]?.get?.(relation)?.name || "";
        }
        return relation.name || relation.display_name || "";
    }

    _get_msp_cloud_country_code(country) {
        if (!country) {
            return "";
        }
        if (typeof country === "string") {
            return country.length === 2 ? country : "";
        }
        if (Array.isArray(country)) {
            const countryRecord = this.pos.models?.["res.country"]?.get?.(country[0]);
            return countryRecord?.code || "";
        }
        if (typeof country === "number") {
            return this.pos.models?.["res.country"]?.get?.(country)?.code || "";
        }
        return country.code || "";
    }

    _build_msp_cloud_cart_item(orderLine, index) {
        if (!orderLine || orderLine.combo_parent_id) {
            return null;
        }

        const product = orderLine.getProduct?.() || orderLine.product_id || {};
        const quantity = Math.abs(
            Number(orderLine.getQuantity?.() ?? orderLine.qty ?? 0)
        );
        if (!quantity) {
            return null;
        }
        const unitPriceExcl = this._get_msp_cloud_unit_price_excl(orderLine, quantity);

        const name =
            orderLine.getFullProductName?.() ||
            orderLine.full_product_name ||
            product.display_name ||
            product.name ||
            _t("POS item");
        const customerNote = orderLine.getCustomerNote?.() || "";
        const discount = Number(orderLine.getDiscount?.() || orderLine.discount || 0);
        const descriptionParts = [];
        if (customerNote) {
            descriptionParts.push(customerNote);
        }
        if (discount) {
            descriptionParts.push(_t("Discount: %s%", discount));
        }

        const item = {
            name,
            description: descriptionParts.join(" | "),
            currency: this.pos.currency.name,
            unit_price: unitPriceExcl,
            quantity,
            merchant_item_id: this._sanitize_msp_cloud_order_id(
                product.default_code ||
                    product.barcode ||
                    product.id ||
                    orderLine.uuid ||
                    `line-${index + 1}`
            ),
        };
        if (this._is_msp_cloud_tip_line(orderLine)) {
            item.msp_cloud_is_tip = true;
        }

        const taxRatePercentage = this._get_msp_cloud_tax_rate_percentage(
            orderLine,
            unitPriceExcl,
            quantity
        );
        if (taxRatePercentage !== null) {
            item.tax_rate_percentage = taxRatePercentage;
        }
        return item;
    }

    _is_msp_cloud_tip_line(orderLine) {
        if (orderLine?.isTipLine?.()) {
            return true;
        }
        const tipProduct = this.pos.config.tip_product_id;
        const tipProductId =
            typeof tipProduct === "number" ? tipProduct : tipProduct?.id;
        const product = orderLine?.getProduct?.() || orderLine?.product_id;
        return Boolean(tipProductId && product?.id === tipProductId);
    }

    _get_msp_cloud_unit_price_excl(orderLine, quantity) {
        if (orderLine.combo_line_ids?.length) {
            const comboTotalExcl = orderLine.combo_line_ids.reduce(
                (total, comboLine) =>
                    total +
                    (this._read_msp_cloud_number(
                        () => comboLine.prices?.total_excluded
                    ) ??
                        this._read_msp_cloud_number(() => comboLine.priceExcl) ??
                        0),
                0
            );
            return this._divide_msp_cloud_amount_by_quantity(comboTotalExcl, quantity);
        }

        const lineTotalExcl =
            this._read_msp_cloud_number(() => orderLine.prices?.total_excluded) ??
            this._read_msp_cloud_number(() => orderLine.priceExcl);
        if (lineTotalExcl !== null) {
            return this._divide_msp_cloud_amount_by_quantity(lineTotalExcl, quantity);
        }

        return Math.abs(
            Number(
                orderLine.displayPriceUnitExcl ??
                    orderLine.unitPrices?.total_excluded ??
                    orderLine.price_unit ??
                    0
            )
        );
    }

    _get_msp_cloud_tax_rate_percentage(orderLine, unitPriceExcl, quantity) {
        const totalPriceExcl =
            this._read_msp_cloud_number(() => orderLine.prices?.total_excluded) ??
            this._read_msp_cloud_number(() => orderLine.priceExcl) ??
            unitPriceExcl * quantity;
        const totalPriceIncl =
            this._read_msp_cloud_number(() => orderLine.prices?.total_included) ??
            this._read_msp_cloud_number(() => orderLine.priceIncl) ??
            this._read_msp_cloud_number(
                () => orderLine.unitPrices?.total_included * quantity
            );
        const lineEffectiveRate = this._compute_msp_cloud_tax_rate_percentage(
            totalPriceIncl,
            totalPriceExcl
        );
        if (lineEffectiveRate !== null) {
            return lineEffectiveRate;
        }

        let unitPriceIncl;
        if (orderLine.combo_line_ids?.length) {
            const comboTotalIncl = orderLine.combo_line_ids.reduce(
                (total, comboLine) =>
                    total +
                    (this._read_msp_cloud_number(
                        () => comboLine.prices?.total_included
                    ) ??
                        this._read_msp_cloud_number(() => comboLine.priceIncl) ??
                        0),
                0
            );
            unitPriceIncl = this._divide_msp_cloud_amount_by_quantity(
                comboTotalIncl,
                quantity
            );
        } else {
            unitPriceIncl =
                this._read_msp_cloud_number(
                    () => orderLine.unitPrices?.total_included
                ) ?? unitPriceExcl;
        }

        const unitEffectiveRate = this._compute_msp_cloud_tax_rate_percentage(
            unitPriceIncl,
            unitPriceExcl
        );
        if (unitEffectiveRate !== null) {
            return unitEffectiveRate;
        }

        const detailsEffectiveRate =
            this._get_msp_cloud_tax_rate_from_tax_details(orderLine);
        if (detailsEffectiveRate !== null) {
            return detailsEffectiveRate;
        }

        const lineTaxRate = this._get_msp_cloud_tax_rate_from_taxes(orderLine?.tax_ids);
        if (lineTaxRate !== null) {
            return lineTaxRate;
        }

        const productTaxRate = this._get_msp_cloud_tax_rate_from_taxes(
            orderLine?.product_id?.taxes_id
        );
        return productTaxRate !== null ? productTaxRate : 0;
    }

    _read_msp_cloud_number(readValue) {
        try {
            const value = Number(readValue());
            return Number.isFinite(value) ? Math.abs(value) : null;
        } catch {
            return null;
        }
    }

    _compute_msp_cloud_tax_rate_percentage(totalIncl, totalExcl) {
        if (!totalExcl || totalIncl === null || totalIncl === undefined) {
            return null;
        }
        const effectiveRate = ((totalIncl - totalExcl) / totalExcl) * 100;
        if (!Number.isFinite(effectiveRate) || effectiveRate < 0) {
            return null;
        }
        return Math.round(effectiveRate * 1000000) / 1000000;
    }

    _get_msp_cloud_tax_rate_from_tax_details(orderLine) {
        const taxesData = orderLine?.prices?.taxes_data;
        if (!Array.isArray(taxesData) || !taxesData.length) {
            return null;
        }

        const totalBase = taxesData.reduce(
            (total, taxData) => total + Math.abs(Number(taxData?.base_amount || 0)),
            0
        );
        const totalTax = taxesData.reduce(
            (total, taxData) => total + Math.abs(Number(taxData?.tax_amount || 0)),
            0
        );
        return this._compute_msp_cloud_tax_rate_percentage(
            totalBase + totalTax,
            totalBase
        );
    }

    _get_msp_cloud_tax_rate_from_taxes(taxes) {
        const taxList = this._to_msp_cloud_array(taxes);
        if (!taxList.length) {
            return null;
        }

        const taxRate = taxList.reduce(
            (total, tax) => total + Number(tax?.amount || 0),
            0
        );
        return Number.isFinite(taxRate) ? Math.max(taxRate, 0) : null;
    }

    _to_msp_cloud_array(value) {
        if (!value) {
            return [];
        }
        if (Array.isArray(value)) {
            return value;
        }
        try {
            return Array.from(value);
        } catch {
            return [];
        }
    }

    _divide_msp_cloud_amount_by_quantity(amount, quantity) {
        return quantity
            ? Math.abs(Number(amount || 0)) / quantity
            : Math.abs(Number(amount || 0));
    }

    _sanitize_msp_cloud_order_id(value) {
        const sanitized = String(value || "")
            .replace(/[^a-zA-Z0-9_-]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 80);
        return sanitized || "pos-order";
    }
}

register_payment_method("multisafepay_cloud", PaymentMultiSafepayCloud);
