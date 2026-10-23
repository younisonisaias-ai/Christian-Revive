"""Christian Revive's own ERP may publish songs by any artist; client
churches' ERPs keep the Artist locked to their ministry name.

Christian Revive's ERP is recognised by a company named with "Revive"
(Chrisitan Revive, Revive Lifestyle). Nothing changes if the switch was
already set.
"""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM ir_config_parameter WHERE key = 'revive.music_any_artist'")
    if cr.fetchone():
        return
    cr.execute("SELECT 1 FROM res_company WHERE name::text ILIKE %s LIMIT 1", ('%revive%',))
    if cr.fetchone():
        cr.execute("""
            INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
            VALUES ('revive.music_any_artist', 'True', 1, 1, now() at time zone 'UTC', now() at time zone 'UTC')
        """)
