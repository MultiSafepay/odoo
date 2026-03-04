{
    "name": "MultiSafepay",
    "summary": """E-commerce is part of our DNA""",
    "author": "MultiSafepay",
    "website": "https://github.com//multisafepay",
    "license": "AGPL-3",
    "category": "Accounting/Payment Providers",
    "version": "18.0.2.0.0",
    "application": True,
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "depends": [
        "payment",
    ],
    "external_dependencies": {"python": ["multisafepay==2.2.0", "requests"]},
    "data": [
        "views/payment_templates.xml",
        "views/payment_provider_views.xml",
        "views/payment_method_views.xml",
        "data/payment_provider_data.xml",
    ],
}
