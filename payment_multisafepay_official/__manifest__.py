{
    'name': 'MultiSafepay',
    'description': '''
        Accept, manage and stimulate online sales with MultiSafepay.
        Increase conversion rates with MultiSafepay unique solutions,
        create the perfect checkout experience and the best payment method mix.
        ''',
    'summary': '''E-commerce is part of our DNA''',
    'author': 'MultiSafepay',
    'website': 'https://www.multisafepay.com',
    'license': 'AGPL-3',
    'category': 'eCommerce',
    'version': '18.0.1.1.0',
    'application': True,
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'depends': [
        'account',
        'payment',
        'stock',
        'sale',
        'website_sale',
    ],
    'external_dependencies': {'python': ['multisafepay']},
    'data': [
        'views/payment_templates.xml',
        'views/payment_provider_views.xml',
        'views/payment_method_views.xml',
        'views/payment_transaction_views.xml',
        'wizard/payment_refund_wizard_views.xml',
        'data/payment_provider_data.xml',
    ],
}
