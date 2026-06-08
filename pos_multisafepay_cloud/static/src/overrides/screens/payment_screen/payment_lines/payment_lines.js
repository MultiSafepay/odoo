import { patch } from "@web/core/utils/patch";
import { PaymentScreenPaymentLines } from "@point_of_sale/app/screens/payment_screen/payment_lines/payment_lines";

patch(PaymentScreenPaymentLines, {
    props: {
        ...PaymentScreenPaymentLines.props,
        refundLines: { type: Array, optional: true },
        selectRefundLine: { type: Function, optional: true },
    },
});

patch(PaymentScreenPaymentLines.prototype, {
    get refundLines() {
        return this.props.refundLines || [];
    },

    selectRefundLine(line) {
        if (this.props.selectRefundLine) {
            this.props.selectRefundLine(line);
        }
    },
});