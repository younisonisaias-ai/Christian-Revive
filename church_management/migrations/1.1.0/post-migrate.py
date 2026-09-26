"""church_management 1.1.0 — move existing check-ins onto church services.

For every OneVoice event that had check-ins, create a matching church.service
(same title, date and location, marked with legacy_onevoice_event_id) and point
the attendance rows at it. Nothing is deleted except the temporary column.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

TABLE = 'church_event_attendance'
TMP = 'legacy_onevoice_event_id_tmp'


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not _column_exists(cr, TABLE, TMP):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Service = env['church.service']

    cr.execute("SELECT to_regclass('onevoice_event')")
    has_onevoice = bool(cr.fetchone()[0])
    has_location = has_onevoice and _column_exists(cr, 'onevoice_event', 'location')

    cr.execute('SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL' % (TMP, TABLE, TMP))
    old_ids = [row[0] for row in cr.fetchall()]

    for old_id in old_ids:
        vals = {
            'name': 'Event #%s' % old_id,
            'service_type': 'special_event',
            'legacy_onevoice_event_id': old_id,
            'is_active': False,
        }
        if has_onevoice:
            cr.execute(
                'SELECT name, date_start%s FROM onevoice_event WHERE id = %%s'
                % (', location' if has_location else ''), (old_id,))
            row = cr.fetchone()
            if row:
                name = row[0]
                if isinstance(name, dict):  # tolerate a translated (jsonb) name
                    name = name.get('en_US') or next(iter(name.values()), None)
                vals['name'] = name or vals['name']
                if row[1]:
                    vals['date_start'] = row[1]
                if has_location and row[2]:
                    vals['location'] = row[2]
        service = Service.create(vals)
        cr.execute('UPDATE %s SET event_id = %%s WHERE %s = %%s' % (TABLE, TMP),
                   (service.id, old_id))

    # Stored related field was computed before the rows had an event.
    cr.execute("""
        UPDATE church_event_attendance a
           SET service_type = s.service_type
          FROM church_service s
         WHERE s.id = a.event_id
    """)
    cr.execute('ALTER TABLE %s DROP COLUMN %s' % (TABLE, TMP))

    cr.execute('SELECT count(*) FROM %s WHERE event_id IS NULL' % TABLE)
    if cr.fetchone()[0] == 0:
        cr.execute('ALTER TABLE %s ALTER COLUMN event_id SET NOT NULL' % TABLE)
    cr.execute("""
        SELECT 1 FROM pg_constraint
         WHERE conname = 'church_event_attendance_event_member_uniq'
    """)
    if not cr.fetchone():
        cr.execute("""
            ALTER TABLE church_event_attendance
              ADD CONSTRAINT church_event_attendance_event_member_uniq
              UNIQUE (event_id, member_id)
        """)
    _logger.info('church_management 1.1.0: moved check-ins for %s event(s) onto church services',
                 len(old_ids))
