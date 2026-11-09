def migrate(cr, version):
    """Existing flat course materials move into one default module per
    course, so nothing a teacher already posted is lost or hidden."""
    # Since 19.0.1.24.0 module names can be translated, so on a database
    # upgraded straight past that version the column already holds JSON.
    cr.execute("""
        SELECT data_type FROM information_schema.columns
         WHERE table_name = 'college_course_module' AND column_name = 'name'
    """)
    row = cr.fetchone()
    name = """'{"en_US": "Course Materials"}'::jsonb""" if row and row[0] == 'jsonb' else "'Course Materials'"
    cr.execute("""
        INSERT INTO college_course_module (course_id, name, sequence, create_date, write_date, create_uid, write_uid)
        SELECT DISTINCT cc.course_id, %s, 10, now(), now(), 1, 1
        FROM college_course_content cc
        WHERE cc.module_id IS NULL
          AND cc.course_id NOT IN (SELECT course_id FROM college_course_module)
    """ % name)
    cr.execute("""
        UPDATE college_course_content cc
           SET module_id = m.id
          FROM college_course_module m
         WHERE cc.module_id IS NULL AND cc.course_id = m.course_id
    """)
