from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestCollegeLogins(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Homiletics', 'program_id': cls.program.id})
        cls.Student = cls.env['college.student']
        cls.student = cls.Student.create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.other = cls.Student.create(
            {'name': 'Daniel', 'email': 'daniel@example.com', 'program_id': cls.program.id})
        cls.enrollment = cls.env['college.enrollment'].create(
            {'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _account(self, student=None, password='good-password'):
        student = student or self.student
        result = self.Student.app_college_student_activate(student.student_code, student._new_signin_code(), password)
        self.assertTrue(result['success'], result)
        return result['session_token']

    def _employee(self, role, email):
        return self.env['hr.employee'].create({
            'name': role, 'staff_role': role, 'is_app_active': True, 'app_email': email, 'app_pin': '4821'})

    def _staff_api(self, role, model='college.enrollment'):
        employee = self.env['hr.employee'].create({'name': role, 'staff_role': role, 'is_app_active': True})
        token = self.env['church.app.session']._issue('staff', employee=employee)
        return self.env[model].with_context(app_staff_session_token=token)

    # ── Students ─────────────────────────────────────────────────

    def test_student_cannot_sign_in_before_getting_a_password(self):
        result = self.Student.app_college_student_sign_in(self.student.student_code, 'anything1')
        self.assertFalse(result['success'])

    def test_code_sets_a_password_and_works_only_once(self):
        code = self.student._new_signin_code()
        first = self.Student.app_college_student_activate(self.student.student_code, code, 'good-password')
        self.assertTrue(first['success'])
        self.assertTrue(self.student.has_password)
        self.assertFalse(self.Student.app_college_student_activate(self.student.student_code, code, 'other-password')['success'])
        self.assertTrue(self.Student.app_college_student_sign_in(self.student.student_code, 'good-password')['success'])
        self.assertFalse(self.Student.app_college_student_sign_in(self.student.student_code, 'bad-password')['success'])

    def test_code_belongs_to_one_student(self):
        code = self.student._new_signin_code()
        self.other._new_signin_code()
        self.assertFalse(self.Student.app_college_student_activate(self.other.student_code, code, 'good-password')['success'])

    def test_expired_code_is_refused(self):
        code = self.student._new_signin_code()
        self.student.sudo().signin_code_expires = fields.Datetime.now() - timedelta(minutes=1)
        result = self.Student.app_college_student_activate(self.student.student_code, code, 'good-password')
        self.assertIn('expired', result['error'])

    def test_short_password_is_refused(self):
        code = self.student._new_signin_code()
        self.assertFalse(self.Student.app_college_student_activate(self.student.student_code, code, 'short')['success'])
        self.assertFalse(self.student.has_password)

    def test_too_many_wrong_passwords_locks_for_a_while(self):
        self._account()
        for _ in range(5):
            self.Student.app_college_student_sign_in(self.student.student_code, 'bad-password')
        result = self.Student.app_college_student_sign_in(self.student.student_code, 'good-password')
        self.assertIn('Too many', result['error'])
        self.student.sudo().locked_until = fields.Datetime.now() - timedelta(minutes=1)
        self.assertTrue(self.Student.app_college_student_sign_in(self.student.student_code, 'good-password')['success'])

    def test_token_shows_only_my_own_studies(self):
        token = self._account()
        data = self.Student.app_college_my_studies(token)['student']
        self.assertEqual(data['code'], self.student.student_code)
        self.assertFalse(self.Student.app_college_my_studies('made-up')['success'])
        self.assertFalse(self.Student.app_college_my_studies(None)['success'])

    def test_sign_out_and_new_password_end_old_sign_ins(self):
        token = self._account()
        self.Student.app_college_student_sign_out(token)
        self.assertFalse(self.Student.app_college_my_studies(token)['success'])
        token = self.Student.app_college_student_sign_in(self.student.student_code, 'good-password')['session_token']
        self._account(password='another-password')
        self.assertFalse(self.Student.app_college_my_studies(token)['success'])

    def test_withdrawn_student_is_shut_out(self):
        token = self._account()
        self.student.state = 'withdrawn'
        self.assertFalse(self.Student.app_college_my_studies(token)['success'])
        self.assertFalse(self.Student.app_college_student_sign_in(self.student.student_code, 'good-password')['success'])

    def test_number_and_email_stop_working_once_a_password_is_set(self):
        code, email = self.student.student_code, 'sarah@example.com'
        self.assertTrue(self.Student.app_college_student_lookup(code, email)['success'])
        self._account()
        self.assertFalse(self.Student.app_college_student_lookup(code, email)['success'])
        self.assertFalse(self.env['college.assignment'].app_college_student_assignments(code, email)['success'])

    def test_number_and_email_can_be_switched_off_for_everyone(self):
        self.env['ir.config_parameter'].sudo().set_param('revive_bible_college.allow_email_lookup', 'False')
        result = self.Student.app_college_student_lookup(self.student.student_code, 'sarah@example.com')
        self.assertFalse(result['success'])

    def test_token_submits_and_downloads_only_for_my_courses(self):
        token = self._account()
        mine = self.env['college.assignment'].create({'name': 'Mine', 'course_id': self.course.id, 'term_id': self.term.id})
        other_course = self.env['college.course'].create({'name': 'Other'})
        theirs = self.env['college.assignment'].create({'name': 'Theirs', 'course_id': other_course.id, 'term_id': self.term.id})
        Assignment = self.env['college.assignment']
        self.assertEqual([a['name'] for a in Assignment.app_college_my_assignments(token)['assignments']], ['Mine'])
        self.assertTrue(Assignment.app_college_my_submit(token, mine.id, text_answer='My answer')['success'])
        self.assertFalse(Assignment.app_college_my_submit(token, mine.id, text_answer='Again')['success'])
        self.assertFalse(Assignment.app_college_my_submit(token, theirs.id, text_answer='No')['success'])
        Content = self.env['college.course.content']
        allowed = Content.create({'name': 'Notes', 'course_id': self.course.id, 'attachment': b'aGVsbG8=', 'attachment_filename': 'n.txt'})
        denied = Content.create({'name': 'Other', 'course_id': other_course.id, 'attachment': b'aGVsbG8=', 'attachment_filename': 'o.txt'})
        self.assertTrue(Content.app_college_my_content(token, allowed.id)['success'])
        self.assertFalse(Content.app_college_my_content(token, denied.id)['success'])

    def test_signin_code_is_for_college_staff_only(self):
        api = self._staff_api('college_staff', 'college.student')
        self.assertTrue(api.app_college_create_signin_code(self.student.id)['signin_code'])
        self.assertFalse(self._staff_api('pastor', 'college.student').app_college_create_signin_code(self.student.id)['success'])
        self.assertFalse(self.Student.app_college_create_signin_code(self.student.id)['success'])

    # ── Staff and admin doors ────────────────────────────────────

    def test_each_staff_role_has_its_own_door(self):
        self._employee('college_staff', 'staff@example.com')
        self._employee('college_admin', 'admin@example.com')
        self._employee('admin', 'church@example.com')
        self._employee('pastor', 'pastor@example.com')
        door = self.Student.app_college_staff_sign_in
        self.assertTrue(door('staff@example.com', '4821', 'staff')['success'])
        self.assertTrue(door('admin@example.com', '4821', 'admin')['success'])
        self.assertTrue(door('church@example.com', '4821', 'admin')['success'])
        self.assertIn('College Staff', door('staff@example.com', '4821', 'admin')['error'])
        self.assertIn('College Admin', door('admin@example.com', '4821', 'staff')['error'])
        self.assertIn('access', door('pastor@example.com', '4821', 'staff')['error'])
        self.assertIn('Invalid', door('staff@example.com', '0000', 'staff')['error'])
        self.assertIn('Invalid', door('staff@example.com', '4821', 'student')['error'])

    def test_a_refused_door_leaves_no_working_session(self):
        employee = self._employee('pastor', 'pastor@example.com')
        Session = self.env['church.app.session'].sudo()
        before = Session.search_count([('employee_id', '=', employee.id), ('revoked', '=', False)])
        self.Student.app_college_staff_sign_in('pastor@example.com', '4821', 'staff')
        self.assertEqual(Session.search_count([('employee_id', '=', employee.id), ('revoked', '=', False)]), before)

    def test_student_token_does_not_open_staff_screens(self):
        token = self._account()
        api = self.env['college.program'].with_context(app_staff_session_token=token)
        self.assertFalse(api.app_college_get_lookups()['success'])

    # ── Grades from the app ──────────────────────────────────────

    def test_staff_submit_and_only_admins_approve(self):
        staff = self._staff_api('college_staff')
        admin = self._staff_api('college_admin')
        self.assertFalse(staff.app_college_grade_action(self.enrollment.id, 'submit', 150)['success'])
        self.assertFalse(staff.app_college_grade_action(self.enrollment.id, 'submit')['success'])
        self.assertTrue(staff.app_college_grade_action(self.enrollment.id, 'submit', 92)['success'])
        self.assertEqual(self.enrollment.grade_state, 'submitted')
        self.assertEqual(self.enrollment.letter_grade, 'A')

        result = staff.app_college_grade_action(self.enrollment.id, 'approve')
        self.assertIn('admin', result['error'])
        self.assertEqual(self.enrollment.grade_state, 'submitted')

        self.assertTrue(admin.app_college_grade_action(self.enrollment.id, 'approve')['success'])
        self.assertFalse(staff.app_college_grade_action(self.enrollment.id, 'publish')['success'])
        self.assertTrue(admin.app_college_grade_action(self.enrollment.id, 'publish')['success'])
        self.assertEqual(self.enrollment.grade_state, 'published')
        self.assertTrue(admin.app_college_grade_action(self.enrollment.id, 'reset')['success'])
        self.assertEqual(self.enrollment.grade_state, 'draft')

    def test_grade_actions_are_refused_outside_the_college(self):
        result = self._staff_api('pastor').app_college_grade_action(self.enrollment.id, 'submit', 90)
        self.assertFalse(result['success'])
        self.assertEqual(self.enrollment.grade_state, 'draft')

    def _erp_user(self, login, *xmlids):
        user = self.env['res.users'].create({'name': login, 'login': login})
        user.group_ids |= self.env['res.groups'].browse([self.env.ref(x).id for x in xmlids])
        self.env['ir.ui.menu'].env.registry.clear_cache()
        return user

    def test_college_only_users_see_only_bible_college(self):
        root = self.env.ref('revive_bible_college.menu_bible_college_root')
        church = self.env['ir.ui.menu'].search([('name', '=', 'Church Management'), ('parent_id', '=', False)], limit=1)
        staff = self._erp_user('only@example.com', 'revive_bible_college.group_college_staff')
        visible = self.env['ir.ui.menu'].with_user(staff)._visible_menu_ids()
        self.assertIn(root.id, visible)
        self.assertNotIn(church.id, visible)
        roots = self.env['ir.ui.menu'].sudo().search([('parent_id', '=', False), ('id', 'in', list(visible))])
        self.assertEqual(roots, root)

    def test_people_with_other_erp_roles_keep_their_menus(self):
        settings = self._erp_user('settings@example.com', 'revive_bible_college.group_college_admin', 'base.group_erp_manager')
        self.assertFalse(settings._is_college_only())
        other = self._erp_user('sales@example.com', 'revive_bible_college.group_college_staff', 'sales_team.group_sale_salesman')
        self.assertFalse(other._is_college_only())
        none = self._erp_user('none@example.com')
        self.assertFalse(none._is_college_only())

    def test_erp_buttons_still_need_the_admin_group(self):
        user = self.env['res.users'].create({
            'name': 'Clerk', 'login': 'test.clerk@example.com',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                  self.env.ref('revive_bible_college.group_college_staff').id])],
        })
        self.enrollment.numeric_grade = 80
        self.enrollment.with_user(user).action_submit_grade()
        with self.assertRaises(UserError):
            self.enrollment.with_user(user).action_approve_grade()
