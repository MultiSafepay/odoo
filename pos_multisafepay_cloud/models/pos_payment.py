from odoo import api, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        return fields + [
            field
            for field in [
                "amount",
                "is_change",
                "pos_order_id",
                "payment_method_id",
                "payment_ref_no",
                "payment_status",
                "ticket",
                "transaction_id",
                "uuid",
            ]
            if field not in fields
        ]