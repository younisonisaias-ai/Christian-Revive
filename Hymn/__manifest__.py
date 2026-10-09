{
    'name': 'Hymn & Song Management',
    'version': '19.0.1.0.1',
    'category': 'Church',
    'summary': 'Manage hymns, songs, geet & zaboor collections with multi-language support',
    'description': """
        Christian Revive - Hymn & Song Management
        ==========================================
        - Multi-collection support (Hymns Book, Geet & Zaboor, custom)
        - Multi-language: English, Urdu, Punjabi, Hindi, Arabic
        - Roman Urdu transliteration for every verse and chorus
        - Category management (worship, praise, salvation, prayer, etc.)
        - Scripture reference linking
        - Tag-based search and filtering
        - Drag-and-drop verse ordering
        - Bulk import from JSON
        - Published/unpublished workflow
        - Collection-level and song-level images
        - API endpoints for Flutter mobile app
    """,
    'author': 'Christian Revive',
    'website': 'https://Christianrevive.com',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/hymn_category_data.xml',
        'views/hymn_collection_views.xml',
        'views/hymn_song_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'sequence': 15,
}