{
    "name": "PoS MultiSafepay Cloud",
    "summary": "PoC for MultiSafepay Cloud POS payments in Odoo POS",
    "author": "MultiSafepay",
    "website": "https://github.com/MultiSafepay/odoo",
    "license": "AGPL-3",
    "category": "Point of Sale",
    "version": "18.0.2.2.1",
    "application": True,
    "depends": [
        "point_of_sale",
    ],
    "external_dependencies": {"python": ["multisafepay==3.1.0", "requests"]},
    "data": [
        "security/ir.model.access.csv",
        "views/pos_payment_method_views.xml",
        "views/pos_multisafepay_cloud_payment_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_multisafepay_cloud/static/src/app/**/*",
        ],
    },
    "installable": True,
}
