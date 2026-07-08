{
    "name": "MultiSafepay Enhanced",
    "description": """
        Enhanced MultiSafepay payment provider with business logic.
        Provides invoice updates, stock/picking management, loyalty integration,
        pricelist filters, reason codes, and advanced validation.
        """,
    "summary": """Advanced MultiSafepay business logic integration""",
    "author": "MultiSafepay",
    "website": "https://github.com//multisafepay",
    "license": "AGPL-3",
    "category": "Sales",
    "version": "19.0.2.2.3",
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
