import { patch } from "@web/core/utils/patch";
import { uniqueBy } from "@point_of_sale/app/models/utils/unique_by";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

patch(PaymentScreen.prototype, {
    get refundLines() {
        const order = this.pos.get_order();
        const orderLinesToRefund = (order?.lines || [])
            .map((line) => line.refunded_orderline_id)
            .filter(Boolean);
        const paymentLinesToRefund = uniqueBy(
            orderLinesToRefund.flatMap((line) => line.order_id?.payment_ids || []),
            (line) => line.id || line.uuid
        );
        const amountDue = Math.abs(order?.get_due?.() || 0);
        const refundIds = this.paymentLines
            .map((line) => line.refundedPaymentId)
            .filter((id) => id != null)
            .map(String);

        return paymentLinesToRefund.filter(
            (line) =>
                amountDue > 0 &&
                line.amount > 0 &&
                !line.is_change &&
                line.payment_method_id?.use_payment_terminal === "multisafepay_cloud" &&
                this.payment_methods_from_config.some(
                    (paymentMethod) => paymentMethod.id === line.payment_method_id.id
                ) &&
                !refundIds.includes(String(line.id || line.uuid))
        );
    },

    async addPaymentLineFromRefundLine(refundLine) {
        const amountToRefund = Math.min(refundLine.amount, Math.abs(this.currentOrder.get_due()));
        if (await this.addNewPaymentLine(refundLine.payment_method_id)) {
            const newPaymentLine = this.paymentLines.at(-1);
            newPaymentLine.set_amount(-amountToRefund);
            newPaymentLine.refundedPaymentId = refundLine.id || refundLine.uuid;
        }
    },
});