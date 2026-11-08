def migrate(cr, version):
    """Existing flat course materials move into one default module per
    course, so nothing a teacher already posted is lost or hidden."""
    cr.execute("""
        INSERT INTO college_course_module (course_id, name, sequence, create_date, write_date, create_uid, write_uid)
        SELECT DISTINCT cc.course_id, 'Course Materials', 10, now(), now(), 1, 1
        FROM college_course_content cc
        WHERE cc.module_id IS NULL
          AND cc.course_id NOT IN (SELECT course_id FROM college_course_module)
    """)
    cr.execute("""
        UPDATE college_course_content cc
           SET module_id = m.id
          FROM college_course_module m
         WHERE cc.module_id IS NULL AND cc.course_id = m.course_id
    """)
