{
    "name": "MultiSafepay Enhanced",
    "summary": """Advanced MultiSafepay business logic integration""",
    "author": "MultiSafepay, Odoo Community Association (OCA)",
    "website": "https://github.com/MultiSafepay/odoo",
    "license": "AGPL-3",
    "category": "Sales",
    "version": "18.0.2.2.1",
    "application": True,
    "depends": [
        "payment_multisafepay",
        "account",
        "stock",
        "sale",
        "sale_stock",
        "sale_management",
    ],
    "external_dependencies": {"python": ["multisafepay==3.1.0", "requests"]},
    "data": [
        "views/payment_method_views.xml",
        "views/payment_transaction_views.xml",
        "wizard/payment_refund_wizard_views.xml",
    ],
}
