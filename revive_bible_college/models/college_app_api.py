"""Shared helper for the Bible College app endpoints (Phase 8: staff side).

Staff sign into the app the same way as every other role — the server reads
who is asking from the signed-in session (church_management's
church.app.session), the same way church.location._app_staff() and
smart_attendance._require_staff() already do. See hr_employee_college.py
for the two roles this module adds.
"""
import re

COLLEGE_ROLES = ('college_staff', 'college_admin', 'admin')
COLLEGE_ADMIN_ROLES = ('college_admin', 'admin')
_CODE_RE = re.compile(r'^([A-Z]*)[\s-]*([0-9]+)$')


def college_app_staff(env):
    """(employee_or_empty, is_admin) for this request's signed-in staff session."""
    session = env['church.app.session']._current_staff()
    staff = session.employee_id if session else env['hr.employee']
    if not staff or not staff.is_app_active or staff.staff_role not in COLLEGE_ROLES:
        return env['hr.employee'], False
    return staff, staff.staff_role in COLLEGE_ADMIN_ROLES


def normalize_code(raw, prefix):
    """A public lookup code, tolerant of someone typing just the digits
    ("00001" or "1"), a missing hyphen ("BC00001"), extra spaces, or
    lowercase, instead of the exact "APP-00001"/"BC-00001". Still requires
    the right prefix letters when any were typed, so an applicant code
    tried on the student lookup (or vice versa) correctly fails rather
    than matching some other record with the same digits."""
    raw = str(raw or '').strip().upper()
    if not raw:
        return raw
    prefix_letters = prefix.rstrip('-')
    match = _CODE_RE.match(raw)
    if not match:
        return raw
    letters, digits = match.group(1), match.group(2)
    if letters and letters != prefix_letters:
        return raw
    return '%s%s' % (prefix, digits.zfill(5))


def public_student(env, code, email):
    """The student matching this code+email pair, or an empty recordset.

    This is how app versions from before student passwords sign in. It stops
    for a student once they set a password, and for everyone when the setting
    revive_bible_college.allow_email_lookup is False."""
    allowed = env['ir.config_parameter'].sudo().get_param('revive_bible_college.allow_email_lookup', 'True')
    if allowed.lower() not in ('1', 'true', 'yes'):
        return env['college.student']
    code = normalize_code(code, 'BC-')
    email = str(email or '').strip().lower()
    if not code or not email:
        return env['college.student']
    return env['college.student'].sudo().search([
        ('student_code', '=ilike', code), ('email', '!=', False), ('has_password', '=', False),
    ], limit=1).filtered(lambda s: s.email.strip().lower() == email)


def token_student(env, token):
    """The student signed in with this token, or an empty recordset."""
    return env['college.student.session'].sudo()._find(token).student_id
