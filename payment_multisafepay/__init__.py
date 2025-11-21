# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

from . import models
from . import controllers
from . import utils

import odoo.addons.payment as payment

def post_init_hook(env):
    payment.setup_provider(env, 'multisafepay')


def uninstall_hook(env):
    payment.reset_payment_provider(env, 'multisafepay')
