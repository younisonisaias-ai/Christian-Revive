"""church_management 1.1.0 — attendance moves from onevoice.event to church.service.

Before the module loads: detach the old event_id column (which points at
onevoice_event) so Odoo can create a fresh event_id pointing at church_service.
The old values are kept in a temporary column and moved across in post-migrate.
"""
import logging

_logger = logging.getLogger(__name__)

TABLE = 'church_event_attendance'
TMP = 'legacy_onevoice_event_id_tmp'


def _column_exists(cr, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (TABLE, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    cr.execute("SELECT to_regclass(%s)", (TABLE,))
    if not cr.fetchone()[0] or not _column_exists(cr, 'event_id') or _column_exists(cr, TMP):
        return

    # Where does event_id currently point?
    cr.execute("""
        SELECT c.conname, ref.relname
          FROM pg_constraint c
          JOIN pg_class ref ON ref.oid = c.confrelid
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
         WHERE c.conrelid = %s::regclass AND c.contype = 'f' AND a.attname = 'event_id'
    """, (TABLE,))
    fkeys = cr.fetchall()
    if any(ref == 'church_service' for _name, ref in fkeys):
        return  # already migrated

    for conname, _ref in fkeys:
        cr.execute('ALTER TABLE %s DROP CONSTRAINT "%s"' % (TABLE, conname))
    cr.execute('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %s_event_member_uniq' % (TABLE, TABLE))
    cr.execute('ALTER TABLE %s RENAME COLUMN event_id TO %s' % (TABLE, TMP))
    cr.execute('ALTER TABLE %s ALTER COLUMN %s DROP NOT NULL' % (TABLE, TMP))
    _logger.info('church_management 1.1.0: detached attendance from onevoice_event')
