"""Plain-Python checks of the Smart Attendance rules.

Run without Odoo:  python -I church_management/tests/test_attendance_rules.py
(Odoo's own test runner uses test_attendance_flow.py instead.)"""
import importlib.util
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / 'models'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rules = _load('_cm_test.attendance_rules', MODELS / 'attendance_rules.py')

# A church in Lahore and points measured from it.
CHURCH = (31.520400, 74.358700)
METRE_LAT = 1 / 111_195  # degrees of latitude per metre


def north(metres):
    return CHURCH[0] + metres * METRE_LAT, CHURCH[1]


class DistanceTests(unittest.TestCase):
    def test_same_point_is_zero(self):
        self.assertAlmostEqual(rules.distance_m(*CHURCH, *CHURCH), 0, places=3)

    def test_known_distance(self):
        # Lahore to Karachi is about 1,030 km.
        km = rules.distance_m(31.5204, 74.3587, 24.8607, 67.0011) / 1000
        self.assertTrue(1020 < km < 1040, km)

    def test_metres_north(self):
        self.assertAlmostEqual(rules.distance_m(*CHURCH, *north(80)), 80, delta=0.5)


class LocationTests(unittest.TestCase):
    def check(self, metres, accuracy, radius=100):
        return rules.check_location(*CHURCH, radius, *north(metres), accuracy)

    def test_inside_radius(self):
        self.assertEqual(self.check(60, 10)[0], rules.LOCATION_OK)

    def test_outside_radius_with_good_accuracy(self):
        result, dist = self.check(400, 10)
        self.assertEqual(result, rules.LOCATION_OUTSIDE)
        self.assertAlmostEqual(dist, 400, delta=1)

    def test_door_with_rough_reading_gets_benefit_of_doubt(self):
        # 130 m away but the phone is only sure within 40 m.
        self.assertEqual(self.check(130, 40)[0], rules.LOCATION_OK)

    def test_allowance_is_capped(self):
        # 180 m with 120 m accuracy: allowance stops at 50 m, so 130 > 100.
        self.assertEqual(self.check(180, 120)[0], rules.LOCATION_OUTSIDE)

    def test_very_poor_accuracy_asks_to_retry(self):
        self.assertEqual(self.check(400, 600)[0], rules.LOCATION_LOW_ACCURACY)

    def test_missing_accuracy_outside_is_low_accuracy(self):
        self.assertEqual(self.check(400, None)[0], rules.LOCATION_LOW_ACCURACY)

    def test_missing_or_bad_coordinates(self):
        self.assertEqual(rules.check_location(*CHURCH, 100, None, None, 5)[0], rules.LOCATION_MISSING)
        self.assertEqual(rules.check_location(*CHURCH, 100, 0, 0, 5)[0], rules.LOCATION_MISSING)
        self.assertEqual(rules.check_location(*CHURCH, 100, 95, 10, 5)[0], rules.LOCATION_MISSING)

    def test_custom_radius(self):
        self.assertEqual(self.check(170, 5, radius=200)[0], rules.LOCATION_OK)
        self.assertEqual(self.check(70, 5, radius=50)[0], rules.LOCATION_OUTSIDE)


START = datetime(2026, 10, 24, 5, 0)  # 10:00 Lahore time, in UTC


class WindowTests(unittest.TestCase):
    def test_defaults(self):
        opens, closes = rules.check_in_window(START)
        self.assertEqual(opens, START - timedelta(minutes=30))
        self.assertEqual(closes, START + timedelta(minutes=60))

    def test_short_event_closes_at_end(self):
        opens, closes = rules.check_in_window(START, START + timedelta(minutes=45))
        self.assertEqual(closes, START + timedelta(minutes=45))

    def test_explicit_close_time_wins(self):
        close_at = START + timedelta(hours=3)
        _, closes = rules.check_in_window(START, START + timedelta(hours=1), close_at=close_at)
        self.assertEqual(closes, close_at)

    def test_states(self):
        opens, closes = rules.check_in_window(START)
        self.assertEqual(rules.window_state(opens - timedelta(minutes=1), opens, closes), 'upcoming')
        self.assertEqual(rules.window_state(opens, opens, closes), 'open')
        self.assertEqual(rules.window_state(START, opens, closes), 'open')
        self.assertEqual(rules.window_state(closes, opens, closes), 'open')
        self.assertEqual(rules.window_state(closes + timedelta(seconds=1), opens, closes), 'closed')

    def test_event_crossing_midnight(self):
        start = datetime(2026, 10, 24, 18, 30)  # 23:30 Lahore
        end = start + timedelta(hours=2)        # ends 01:30 next day
        opens, closes = rules.check_in_window(start, end, 30, 90)
        self.assertEqual(rules.window_state(start + timedelta(minutes=80), opens, closes), 'open')

    def test_never_closes_before_opening(self):
        opens, closes = rules.check_in_window(START, close_at=START - timedelta(hours=2))
        self.assertGreaterEqual(closes, opens)


class LateTests(unittest.TestCase):
    def test_grace(self):
        self.assertFalse(rules.is_late(START + timedelta(minutes=10), START))
        self.assertTrue(rules.is_late(START + timedelta(minutes=11), START))
        self.assertFalse(rules.is_late(START + timedelta(minutes=20), START, 30))


class OfflineTests(unittest.TestCase):
    now = datetime(2026, 10, 24, 6, 0)

    def test_recent_capture_is_fine(self):
        self.assertIsNone(rules.offline_capture_problem(self.now - timedelta(hours=1), self.now))

    def test_future_capture_rejected(self):
        self.assertEqual(rules.offline_capture_problem(self.now + timedelta(minutes=30), self.now),
                         'future_time')

    def test_small_clock_drift_allowed(self):
        self.assertIsNone(rules.offline_capture_problem(self.now + timedelta(minutes=3), self.now))

    def test_old_capture_rejected(self):
        self.assertEqual(rules.offline_capture_problem(self.now - timedelta(hours=13), self.now),
                         'too_old')

    def test_missing_time(self):
        self.assertEqual(rules.offline_capture_problem(None, self.now), 'missing_time')


TODAY = date(2026, 10, 24)


def person(pid, **kw):
    base = {'id': pid, 'family_id': 1, 'is_family_head': False, 'relationship': False,
            'verified': True, 'guardian_id': False, 'date_of_birth': None}
    base.update(kw)
    return base


class FamilyTests(unittest.TestCase):
    head = person(1, is_family_head=True)
    wife = person(2, relationship='spouse')
    son = person(3, relationship='son', date_of_birth=date(2016, 5, 1))
    adult_son = person(4, relationship='son', date_of_birth=date(1998, 5, 1))
    brother = person(5, relationship='brother')

    def allowed(self, acting, attendee):
        return rules.family_permission(acting, attendee, TODAY)[0]

    def test_self(self):
        self.assertTrue(self.allowed(self.brother, self.brother))

    def test_head_checks_in_spouse_and_child(self):
        self.assertTrue(self.allowed(self.head, self.wife))
        self.assertTrue(self.allowed(self.head, self.son))

    def test_spouse_checks_in_head_and_child(self):
        self.assertTrue(self.allowed(self.wife, self.head))
        self.assertTrue(self.allowed(self.wife, self.son))

    def test_not_adult_children(self):
        self.assertEqual(rules.family_permission(self.head, self.adult_son, TODAY), (False, 'adult'))

    def test_child_without_birthday_counts_as_dependent(self):
        self.assertTrue(self.allowed(self.head, person(6, relationship='daughter')))

    def test_not_other_adults(self):
        self.assertFalse(self.allowed(self.head, self.brother))

    def test_child_cannot_check_in_parent(self):
        self.assertFalse(self.allowed(self.son, self.head))

    def test_other_family(self):
        other = person(9, family_id=2, relationship='son')
        self.assertEqual(rules.family_permission(self.head, other, TODAY), (False, 'not_family'))

    def test_unverified_relative(self):
        pending = person(7, relationship='son', verified=False)
        self.assertEqual(rules.family_permission(self.head, pending, TODAY), (False, 'not_verified'))

    def test_guardian_outside_family(self):
        ward = person(8, family_id=5, guardian_id=1)
        self.assertTrue(self.allowed(self.head, ward))

    def test_no_family(self):
        loner = person(10, family_id=False)
        self.assertFalse(self.allowed(loner, self.son))


if __name__ == '__main__':
    unittest.main(verbosity=1)
