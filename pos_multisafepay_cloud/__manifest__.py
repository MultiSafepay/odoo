{
    "name": "POS MultiSafepay Cloud",
    "summary": "MultiSafepay Cloud POS payments in Odoo POS",
    "author": "MultiSafepay",
    "website": "https://www.multisafepay.com/",
    "license": "AGPL-3",
    "category": "Point of Sale",
    "version": "20.0.3.0.0",
    "application": True,
    "depends": [
        "point_of_sale",
        "payment_multisafepay_official",
    ],
    "external_dependencies": {"python": ["multisafepay==3.1.0", "requests"]},
    "data": [
        # migracion_19_20: ir.model.access was replaced by ir.access in Odoo 20; the CSV
        # is named ir.access.csv and uses the operation/domain columns.
        "security/ir.access.csv",
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_multisafepay_cloud/static/src/app/**/*",
        ],
        "web.assets_backend": [
            "pos_multisafepay_cloud/static/src/backend/**/*",
        ],
    },
    "installable": True,
}
