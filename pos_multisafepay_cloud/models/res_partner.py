# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _load_pos_data_fields(self, config):
        fields = super()._load_pos_data_fields(config)
        if "mobile" not in fields:
            fields.append("mobile")
        return fields
