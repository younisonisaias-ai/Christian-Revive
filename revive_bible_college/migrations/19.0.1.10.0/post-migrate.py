def migrate(cr, version):
    """Ungraded enrollments were saved with a letter grade of F. Clear those."""
    cr.execute("""
        UPDATE college_enrollment
           SET letter_grade = NULL
         WHERE grade_state = 'draft'
           AND COALESCE(numeric_grade, 0) = 0
           AND letter_grade = 'F'
    """)
