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
    "category": "eCommerce",
    "version": "19.0.1.1.0",
    "application": True,
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "depends": [
        "payment",
    ],
    "external_dependencies": {"python": ["multisafepay"]},
    "data": [
        "views/payment_templates.xml",
        "views/payment_provider_views.xml",
        "views/payment_method_views.xml",
        "data/payment_provider_data.xml",
    ],
}
