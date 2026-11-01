"""Shared helper for the Bible College app endpoints (Phase 8: staff side).

Staff sign into the app the same way as every other role — the server reads
who is asking from the signed-in session (church_management's
church.app.session), the same way church.location._app_staff() and
smart_attendance._require_staff() already do. See hr_employee_college.py
for the two roles this module adds.
"""

COLLEGE_ROLES = ('college_staff', 'college_admin')


def college_app_staff(env):
    """(employee_or_empty, is_admin) for this request's signed-in staff session."""
    session = env['church.app.session']._current_staff()
    staff = session.employee_id if session else env['hr.employee']
    if not staff or not staff.is_app_active or staff.staff_role not in COLLEGE_ROLES:
        return env['hr.employee'], False
    return staff, staff.staff_role == 'college_admin'
