import {patch} from "@web/core/utils/patch";
import {PosPaymentProviderCards} from "@point_of_sale/backend/pos_payment_provider_cards/pos_payment_provider_cards";
import {onWillStart} from "@odoo/owl";

patch(PosPaymentProviderCards.prototype, {
    setup() {
        super.setup();
        onWillStart(async () => {
            const res = await this.orm.call(
                "pos.payment.method",
                "get_provider_status",
                [["pos_multisafepay_cloud"]]
            );
            const status = res.state.find((p) => p.name === "pos_multisafepay_cloud");
            if (status) {
                // Prevent duplicate addition if it's already there
                if (
                    !this.state.providers.some(
                        (p) => p.selection === "multisafepay_cloud"
                    )
                ) {
                    this.state.providers.push(
                        Object.assign(
                            {
                                selection: "multisafepay_cloud",
                                provider: "MultiSafepay Cloud POS",
                            },
                            status
                        )
                    );
                }
            }
        });
    },
});
