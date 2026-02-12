{
    "name": "MultiSafepay Enhanced",
    "summary": """Advanced MultiSafepay business logic integration""",
    "author": "MultiSafepay",
    "website": "https://github.com//multisafepay",
    "license": "AGPL-3",
    "category": "eCommerce",
    "version": "18.0.2.0.0",
    "application": True,
    "depends": [
        "payment_multisafepay",
        "account",
        "stock",
        "sale",
        "sale_stock",
        "sale_management",
    ],
    "external_dependencies": {"python": ["multisafepay"]},
    "data": [
        "views/payment_method_views.xml",
        "views/payment_transaction_views.xml",
        "wizard/payment_refund_wizard_views.xml",
    ],
}
