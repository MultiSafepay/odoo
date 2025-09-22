# Copyright (c) MultiSafepay, Inc. All rights reserved.
# This file is licensed under the GNU Affero General Public License (AGPL) version 3.0.
# See the LICENSE.md file for more information.
# See the DISCLAIMER.md file for disclaimer details

SUPPORTED_CURRENCIES = [
    'AED',
    'AUD',
    'BGN',
    'BRL',
    'CAD',
    'CHF',
    'CLP',
    'CNY',
    'COP',
    'CZK',
    'DKK',
    'EUR',
    'GBP',
    'HKD',
    'HRK',
    'HUF',
    'ILS',
    'INR',
    'ISK',
    'JPY',
    'KRW',
    'MXN',
    'MYR',
    'NOK',
    'NZD',
    'PEN',
    'PHP',
    'PLN',
    'RON',
    'RUB',
    'SEK',
    'SGD',
    'THB',
    'TRY',
    'TWD',
    'USD',
    'VEF',
    'ZAR'
]

STATUS_MAPPING = {
    'draft': ('initialized',),
    'pending': (),
    'authorized': ('reserved',),
    'done': ('completed', 'partial_refunded', 'refunded', 'uncleared'),
    'cancel': ('canceled', 'cancelled', 'void', 'expired'),
    'error': ('declined', 'chargedback', 'charged_back'),
}

PAYMENT_METHOD_PENDING = [
    'bank_transfer',
    'multibanco',
]

PAYMENT_METHOD_CODES = {
    'bancontact': 'mistercash',
    'bank_transfer': 'banktrans',
    'kbc_cbc': 'kbc',
    'wechat_pay': 'wechat',
}

BNPL_METHODS = [
    'afterpay',
    'einvoice',
    'in3',
    'klarna',
    'payafter',
    'bnpl_instm',
    'bnpl_inst',
    'in3b2b',
    'santander',
    'zinia',
    'zinia_in3',
    'bnpl_ob',
    'bnpl_mf',
    'billink',
]
