{
    "name": "POS Charge to Room (Hotel Folio)",
    "summary": "Charge Point of Sale orders to a checked-in guest's hotel folio",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "license": "LGPL-3",
    "author": "Eden",
    "depends": ["point_of_sale", "hotel"],
    "data": [
        "views/pos_payment_method_views.xml",
        "views/pos_order_views.xml",
        "views/hotel_folio_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_hotel_room_charge/static/src/app/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
