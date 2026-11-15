{
    "name": "Hotel - Sirvoy booking webhook",
    "summary": "Create a guest and an open folio when Sirvoy reports a check-in",
    "version": "19.0.1.0.0",
    "category": "Generic Modules/Hotel Management",
    "license": "LGPL-3",
    "author": "Eden",
    "depends": ["hotel"],
    "data": [
        "security/ir.model.access.csv",
        "views/sirvoy_webhook_event_views.xml",
        "views/hotel_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
