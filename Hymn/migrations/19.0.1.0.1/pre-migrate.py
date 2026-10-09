"""Merge duplicate hymn categories (same code) before the unique rule is enforced.

For each duplicated code the copy with the most songs is kept; songs are moved
onto it, the module's XML id is pointed at it, and the empty copies are removed.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT c.code, c.id, COUNT(s.id) AS songs
          FROM hymn_category c
          LEFT JOIN hymn_song s ON s.category_id = c.id
         WHERE c.code IN (SELECT code FROM hymn_category GROUP BY code HAVING COUNT(*) > 1)
         GROUP BY c.code, c.id
         ORDER BY c.code, songs DESC, c.id
    """)
    groups = {}
    for code, cat_id, _songs in cr.fetchall():
        groups.setdefault(code, []).append(cat_id)
    for code, ids in groups.items():
        keep, drop = ids[0], ids[1:]
        cr.execute("UPDATE hymn_song SET category_id = %s WHERE category_id = ANY(%s)", (keep, drop))
        cr.execute("""UPDATE ir_model_data SET res_id = %s
                       WHERE model = 'hymn.category' AND res_id = ANY(%s)""", (keep, drop))
        cr.execute("DELETE FROM hymn_category WHERE id = ANY(%s)", (drop,))
        _logger.info('Hymn: merged duplicate category %r into id %s (removed %s)', code, keep, drop)
