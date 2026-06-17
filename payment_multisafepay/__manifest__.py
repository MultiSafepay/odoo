{
    "name": "MultiSafepay",
    "description": """
        Accept, manage and stimulate online sales with MultiSafepay.
        Increase conversion rates with MultiSafepay unique solutions,
        create the perfect checkout experience and the best payment method mix.
        """,
    "summary": """E-commerce is part of our DNA""",
    "author": "MultiSafepay",
    "website": "https://github.com//multisafepay",
    "license": "AGPL-3",
    "category": "Accounting/Payment Providers",
    "version": "19.0.2.2.3",
    "application": True,
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "depends": [
        "payment",
    ],
    "external_dependencies": {"python": ["multisafepay==3.0.0", "requests"]},
    "data": [
        "views/payment_templates.xml",
        "views/payment_provider_views.xml",
        "views/payment_method_views.xml",
        "data/payment_provider_data.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "payment_multisafepay/static/src/interactions/apple_pay_visibility.js",
        ],
    },
}
