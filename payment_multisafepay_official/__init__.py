# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from . import models
from . import controllers
from . import utils

import odoo.addons.payment as payment


def post_init_hook(env):
    payment.setup_provider(env, "multisafepay")


def uninstall_hook(env):
    payment.reset_payment_provider(env, "multisafepay")


def pre_init_hook(env):
    cr = env.cr
    # Check if payment_multisafepay is registered in the database
    cr.execute("SELECT state FROM ir_module_module WHERE name = 'payment_multisafepay'")
    res = cr.fetchone()
    if res:
        # Re-associate all models/views/data references from the old module name to the new one
        cr.execute("""
            UPDATE ir_model_data
            SET module = 'payment_multisafepay_official'
            WHERE module = 'payment_multisafepay'
        """)
        cr.execute("""
            UPDATE ir_module_module_dependency
            SET name = 'payment_multisafepay_official'
            WHERE name = 'payment_multisafepay'
        """)
        # Remove base metadata tracking for the old module name
        cr.execute("""
            DELETE FROM ir_model_data
            WHERE name = 'module_payment_multisafepay'
              AND module = 'base'
              AND model = 'ir.module.module'
        """)
        # Finally, delete the old module record since its references are now mapped to the new one
        cr.execute("DELETE FROM ir_module_module WHERE name = 'payment_multisafepay'")
