"""Smart Attendance end to end, inside Odoo.

Run on the server:
  odoo -d <db> -u church_management --test-tags /church_management --stop-after-init
Plain rules (no database) are in test_attendance_rules.py.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

# Points measured from the church; about 1 m per 0.000009 degrees of latitude.
LAT, LON = 31.5204, 74.3587


def north(metres):
    return LAT + metres / 111_195


@tagged('post_install', '-at_install')
class TestSmartAttendance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.Attendance = env['church.event.attendance']
        cls.Session = env['church.app.session']
        cls.location = env['church.location'].create({
            'name': 'Test Church', 'latitude': LAT, 'longitude': LON, 'geofence_radius_m': 100,
        })
        Partner = env['res.partner']
        cls.family = env['church.family'].create({'name': 'Romeo Family'})
        cls.head = Partner.create({'name': 'Head Romeo', 'is_member': True,
                                   'family_id': cls.family.id, 'is_family_head': True})
        cls.wife = Partner.create({'name': 'Wife Romeo', 'is_member': True,
                                   'family_id': cls.family.id, 'family_relationship': 'spouse'})
        cls.child = Partner.create({'name': 'Child Romeo', 'is_member': True,
                                    'family_id': cls.family.id, 'family_relationship': 'son',
                                    'date_of_birth': date.today() - timedelta(days=365 * 9)})
        cls.adult_son = Partner.create({'name': 'Adult Romeo', 'is_member': True,
                                        'family_id': cls.family.id, 'family_relationship': 'son',
                                        'date_of_birth': date.today() - timedelta(days=365 * 25)})
        cls.stranger = Partner.create({'name': 'Someone Else', 'is_member': True})
        now = fields.Datetime.now()
        cls.service = env['church.service'].create({
            'name': 'Divine Worship', 'date_start': now + timedelta(minutes=10),
            'date_end': now + timedelta(minutes=100), 'location_id': cls.location.id,
        })
        cls.youth = env['church.service'].create({
            'name': 'Children Bible School', 'service_type': 'children',
            'date_start': now + timedelta(minutes=5), 'date_end': now + timedelta(minutes=65),
            'location_id': cls.location.id,
        })
        cls.head_token = cls.Session._issue('member', partner=cls.head)
        cls.staff = env['hr.employee'].create({
            'name': 'Usher', 'staff_role': 'pastor', 'is_app_active': True,
            'app_email': 'usher@example.invalid', 'app_pin': '4321'})
        cls.staff_token = cls.Session._issue('staff', employee=cls.staff)

    def as_head(self):
        return self.Attendance.with_context(app_session_token=self.head_token)

    def as_staff(self):
        return self.Attendance.with_context(app_staff_session_token=self.staff_token)

    def check_in(self, people, service=None, metres=20, accuracy=10, **kw):
        service = service or self.service
        items = [{'member_id': p.id, 'service_id': service.id} for p in people]
        return self.as_head().app_attendance_check_in(
            items, latitude=north(metres), longitude=LON, accuracy=accuracy, **kw)

    # ── Sessions ────────────────────────────────────────────────

    def test_no_token_no_check_in(self):
        result = self.Attendance.app_attendance_check_in(
            [{'member_id': self.head.id, 'service_id': self.service.id}], LAT, LON, 10)
        self.assertEqual(result['error'], 'sign_in_required')

    def test_revoked_token_refused(self):
        token = self.Session._issue('member', partner=self.head)
        self.Session.sudo().search([], order='id desc', limit=1).revoked = True
        result = self.Attendance.with_context(app_session_token=token).app_attendance_home()
        self.assertFalse(result['success'])

    def test_named_member_must_match_token(self):
        Partner = self.env['res.partner'].with_context(app_session_token=self.head_token)
        self.assertEqual(Partner._church_caller_scope(requester_partner_id=self.stranger.id)[0], 'denied')
        self.assertEqual(Partner._church_caller_scope(requester_partner_id=self.head.id)[0], 'self')

    def test_staff_sign_in_checks_pin_on_server(self):
        bad = self.Session.app_staff_sign_in('usher@example.invalid', '0000')
        self.assertFalse(bad['success'])
        good = self.Session.app_staff_sign_in('USHER@example.invalid', '4321')
        self.assertTrue(good['success'])
        self.assertTrue(good['session_token'])

    # ── Member and family check-in ──────────────────────────────

    def test_self_check_in_inside_radius(self):
        result = self.check_in(self.head)
        self.assertEqual(len(result['successful']), 1)
        record = self.Attendance.browse(result['successful'][0]['attendance_id'])
        self.assertEqual(record.method, 'geofence_self')
        self.assertTrue(record.location_verified)
        self.assertEqual(record.verification, 'live')

    def test_family_check_in(self):
        result = self.check_in(self.head | self.wife | self.child)
        self.assertEqual(len(result['successful']), 3)
        self.assertEqual(self.Attendance.browse(result['successful'][2]['attendance_id']).method,
                         'geofence_family')

    def test_head_checks_in_adult_child_but_not_strangers(self):
        result = self.check_in(self.head | self.stranger | self.adult_son)
        self.assertEqual(len(result['successful']), 2)
        reasons = {f['member_id']: f['reason'] for f in result['failed']}
        self.assertEqual(reasons, {self.stranger.id: 'not_family'})

    def test_outside_radius_refused_and_logged(self):
        result = self.check_in(self.head, metres=900)
        self.assertEqual(result['failed'][0]['reason'], 'location_outside')
        self.assertTrue(self.env['church.attendance.log'].search([
            ('action', '=', 'location_failed'), ('service_id', '=', self.service.id)]))

    def test_poor_accuracy_asks_to_retry(self):
        result = self.check_in(self.head, metres=400, accuracy=800)
        self.assertEqual(result['failed'][0]['reason'], 'location_low_accuracy')

    def test_duplicate_is_already(self):
        self.check_in(self.head)
        again = self.check_in(self.head)
        self.assertEqual(len(again['already']), 1)
        self.assertEqual(self.Attendance.search_count([('event_id', '=', self.service.id),
                                                       ('member_id', '=', self.head.id)]), 1)

    def test_double_tap_same_key_replays(self):
        first = self.check_in(self.head | self.wife, idempotency_key='abc123')
        second = self.check_in(self.head | self.wife, idempotency_key='abc123')
        self.assertTrue(second.get('replayed'))
        self.assertEqual({s['attendance_id'] for s in first['successful']},
                         {s['attendance_id'] for s in second['successful']})

    def test_one_family_member_already_checked_in(self):
        self.check_in(self.wife)
        result = self.check_in(self.head | self.wife)
        self.assertEqual(len(result['successful']), 1)
        self.assertEqual(len(result['already']), 1)

    def test_multiple_events_per_person(self):
        result = self.as_head().app_attendance_check_in([
            {'member_id': self.head.id, 'service_id': self.service.id},
            {'member_id': self.child.id, 'service_id': self.youth.id},
        ], latitude=north(10), longitude=LON, accuracy=8)
        self.assertEqual(len(result['successful']), 2)

    def test_window_not_open_yet_and_closed(self):
        later = self.env['church.service'].create({
            'name': 'Evening', 'date_start': fields.Datetime.now() + timedelta(hours=5),
            'location_id': self.location.id})
        self.assertEqual(self.check_in(self.head, service=later)['failed'][0]['reason'], 'upcoming')
        earlier = self.env['church.service'].create({
            'name': 'Morning', 'date_start': fields.Datetime.now() - timedelta(hours=5),
            'location_id': self.location.id})
        self.assertEqual(self.check_in(self.head, service=earlier)['failed'][0]['reason'], 'closed')

    def test_service_lists_say_when_check_in_opens(self):
        tomorrow = self.env['church.service'].create({
            'name': 'Tomorrow', 'date_start': fields.Datetime.now() + timedelta(days=1),
            'location_id': self.location.id})
        Service = self.env['church.service'].with_context(app_staff_session_token=self.staff_token)
        listed = {s['id']: s for s in Service.app_get_services(
            requester_staff_id=self.staff.id)['services']}
        self.assertEqual(listed[tomorrow.id]['checkin_state'], 'upcoming')
        self.assertEqual(listed[tomorrow.id]['checkin_opens'],
                         fields.Datetime.to_string(tomorrow._checkin_window()[0]))
        self.assertEqual(listed[self.service.id]['checkin_state'], 'open')

    def test_cancelled_event(self):
        self.service.cancelled = True
        self.assertEqual(self.check_in(self.head)['failed'][0]['reason'], 'cancelled')

    def test_late_marked(self):
        self.service.write({'date_start': fields.Datetime.now() - timedelta(minutes=30),
                            'checkin_close_minutes_after_start': 60})
        result = self.check_in(self.head)
        self.assertTrue(result['successful'][0]['is_late'])

    def test_offline_attempt(self):
        captured = fields.Datetime.to_string(fields.Datetime.now() - timedelta(minutes=2))
        ok = self.check_in(self.head, offline=True, captured_at=captured)
        record = self.Attendance.browse(ok['successful'][0]['attendance_id'])
        self.assertEqual(record.verification, 'offline')
        old = fields.Datetime.to_string(fields.Datetime.now() - timedelta(hours=20))
        self.assertEqual(self.check_in(self.wife, offline=True, captured_at=old)['failed'][0]['reason'],
                         'offline_too_old')

    def test_no_location_stored(self):
        result = self.check_in(self.head)
        record = self.Attendance.browse(result['successful'][0]['attendance_id'])
        stored = record.read()[0]
        self.assertNotIn('latitude', stored)
        self.assertTrue(record.distance_m < 100)

    def test_home_shows_open_events_and_household(self):
        home = self.as_head().app_attendance_home(latitude=north(10), longitude=LON, accuracy=10)
        self.assertTrue(home['success'])
        self.assertEqual(home['at_church'], 'Test Church')
        self.assertIn(self.service.id, [e['service_id'] for e in home['open']])
        rows = {h['member_id']: h for h in home['household']}
        self.assertTrue(rows[self.child.id]['can_check_in'])
        # The family head checks in the whole family, adult children too.
        self.assertTrue(rows[self.adult_son.id]['can_check_in'])
        self.assertTrue(home['at_location_ids'])
        event = next(e for e in home['open'] if e['service_id'] == self.service.id)
        self.assertIn('checked_in_total', event)
        self.assertIn('description', event)

    # ── Staff ───────────────────────────────────────────────────

    def test_staff_manual_check_in_and_remove(self):
        result = self.as_staff().app_attendance_staff_check_in(self.service.id, [self.stranger.id],
                                                               notes='Phone had no location')
        attendance_id = result['successful'][0]['attendance_id']
        record = self.Attendance.browse(attendance_id)
        self.assertEqual(record.method, 'staff_manual')
        self.assertEqual(record.verification, 'staff')
        no_reason = self.as_staff().app_attendance_update(attendance_id, status='removed')
        self.assertFalse(no_reason['success'])
        removed = self.as_staff().app_attendance_update(attendance_id, status='removed',
                                                        reason='Checked in by mistake')
        self.assertEqual(removed['status'], 'removed')
        # Checking in again brings the record back rather than duplicating it.
        again = self.as_staff().app_attendance_staff_check_in(self.service.id, [self.stranger.id])
        self.assertEqual(again['successful'][0]['attendance_id'], attendance_id)

    def test_staff_endpoints_need_staff_token(self):
        self.assertFalse(self.as_head().app_attendance_staff_services()['success'])
        self.assertTrue(self.as_staff().app_attendance_staff_services()['success'])

    def test_guest(self):
        result = self.as_staff().app_attendance_add_guest(self.service.id, 'First Visitor', '+92300000')
        record = self.Attendance.browse(result['successful'][0]['attendance_id'])
        self.assertEqual(record.attendee_kind, 'guest')

    def test_counts(self):
        self.check_in(self.head | self.child)
        detail = self.as_staff().app_attendance_service_detail(self.service.id)
        self.assertEqual(detail['counts']['total'], 2)
        self.assertEqual(detail['counts']['children'], 1)
        self.assertEqual(detail['counts']['families'], 1)

    # ── Older app versions ─────────────────────────────────────

    def test_legacy_staff_qr_check_in(self):
        result = self.Attendance.with_context(app_staff_session_token=self.staff_token).app_check_in(
            member_id=self.wife.id, requester_staff_id=self.staff.id,
            service_id=self.service.id, method='qr')
        self.assertTrue(result['success'])
        record = self.Attendance.browse(result['attendance_id'])
        self.assertEqual(record.method, 'qr')

    def test_legacy_self_check_in_needs_location_event_off(self):
        result = self.Attendance.with_context(app_session_token=self.head_token).app_check_in(
            member_id=self.head.id, requester_partner_id=self.head.id, service_id=self.service.id)
        self.assertFalse(result['success'])
        self.service.geofence_required = False
        result = self.Attendance.with_context(app_session_token=self.head_token).app_check_in(
            member_id=self.head.id, requester_partner_id=self.head.id, service_id=self.service.id)
        self.assertTrue(result['success'])
        self.assertEqual(self.Attendance.browse(result['attendance_id']).method, 'member_manual')

    # ── Schedules copy settings ────────────────────────────────

    def test_schedule_copies_settings(self):
        schedule = self.env['church.service.schedule'].create({
            'name': 'Weekly Prayer', 'weekday': '2', 'start_time': 19.0,
            'location_id': self.location.id, 'grace_minutes': 25, 'family_checkin_enabled': False,
        })
        service = schedule.service_ids[:1]
        self.assertTrue(service)
        self.assertEqual(service.location_id, self.location)
        self.assertEqual(service.grace_minutes, 25)
        self.assertFalse(service.family_checkin_enabled)
