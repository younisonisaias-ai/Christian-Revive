"""Smart Attendance rules that need no database, so they can be tested alone.

Everything here takes plain values (UTC datetimes without tzinfo, metres,
degrees) and returns plain values. The models call these; the tests in
tests/test_attendance_rules.py run them without Odoo.
"""
import math
from datetime import timedelta

EARTH_RADIUS_M = 6371008.8

DEFAULT_RADIUS_M = 100
DEFAULT_OPEN_MINUTES_BEFORE = 30
DEFAULT_CLOSE_MINUTES_AFTER_START = 60
DEFAULT_GRACE_MINUTES = 10

# A reading whose accuracy circle is wider than this cannot tell "inside the
# church" from "down the road"; the member is asked to try again, not refused.
MAX_USABLE_ACCURACY_M = 150
# Part of the accuracy circle given the benefit of the doubt, so a member
# standing at the door with a 40 m reading is not turned away. Capped so a
# poor reading cannot stretch the radius far.
ACCURACY_ALLOWANCE_CAP_M = 50

# Offline attempts are accepted only if taken recently, and never "from the
# future" beyond small phone clock drift.
OFFLINE_MAX_AGE = timedelta(hours=12)
CLOCK_DRIFT = timedelta(minutes=5)

LOCATION_OK = 'ok'
LOCATION_OUTSIDE = 'outside'
LOCATION_LOW_ACCURACY = 'low_accuracy'
LOCATION_MISSING = 'missing'


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres (Haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def valid_coordinates(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0)


def check_location(church_lat, church_lon, radius_m, lat, lon, accuracy_m):
    """Is a reading at the church?

    Returns (result, distance_m). result is LOCATION_OK, LOCATION_OUTSIDE,
    LOCATION_LOW_ACCURACY or LOCATION_MISSING. A reading counts as inside when
    the distance minus a capped share of its accuracy is within the radius.
    """
    if lat is None or lon is None or not valid_coordinates(lat, lon):
        return LOCATION_MISSING, None
    dist = distance_m(float(church_lat), float(church_lon), float(lat), float(lon))
    try:
        accuracy = max(0.0, float(accuracy_m)) if accuracy_m is not None else None
    except (TypeError, ValueError):
        accuracy = None
    radius = float(radius_m or DEFAULT_RADIUS_M)
    allowance = min(accuracy or 0.0, ACCURACY_ALLOWANCE_CAP_M)
    if dist - allowance <= radius:
        return LOCATION_OK, dist
    if accuracy is None or accuracy > MAX_USABLE_ACCURACY_M:
        # Could be inside; the reading is too rough to say. Ask to retry.
        return LOCATION_LOW_ACCURACY, dist
    return LOCATION_OUTSIDE, dist


def check_in_window(start, end=None, open_minutes_before=None,
                    close_minutes_after_start=None, close_at=None):
    """(opens, closes) for an event occurrence, all naive UTC.

    close_at wins over close_minutes_after_start. The window never closes
    before it opens, and never later than the event's end when no explicit
    close time is set and the end comes first.
    """
    before = DEFAULT_OPEN_MINUTES_BEFORE if open_minutes_before is None else max(0, open_minutes_before)
    after = DEFAULT_CLOSE_MINUTES_AFTER_START if close_minutes_after_start is None \
        else max(0, close_minutes_after_start)
    opens = start - timedelta(minutes=before)
    if close_at:
        closes = close_at
    else:
        closes = start + timedelta(minutes=after)
        if end and end > start:
            closes = min(closes, end)
    return opens, max(closes, opens)


def window_state(now, opens, closes):
    """'upcoming', 'open' or 'closed' at server time `now`."""
    if now < opens:
        return 'upcoming'
    if now > closes:
        return 'closed'
    return 'open'


def is_late(check_in_at, start, grace_minutes=None):
    grace = DEFAULT_GRACE_MINUTES if grace_minutes is None else max(0, grace_minutes)
    return check_in_at > start + timedelta(minutes=grace)


def offline_capture_problem(captured_at, server_now):
    """Why an offline attempt cannot be accepted, or None.

    The check-in time of an offline attempt is when the phone captured it;
    the server still checks that time against the event window.
    """
    if captured_at is None:
        return 'missing_time'
    if captured_at > server_now + CLOCK_DRIFT:
        return 'future_time'
    if server_now - captured_at > OFFLINE_MAX_AGE:
        return 'too_old'
    return None


def is_minor(date_of_birth, today):
    """True when known to be under 18; False when 18+; None when unknown."""
    if not date_of_birth:
        return None
    years = today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    return years < 18


CHILD_RELATIONSHIPS = ('son', 'daughter', 'grandchild')


def family_permission(acting, attendee, today):
    """May `acting` check `attendee` in? Returns (allowed, reason).

    Both are dicts: id, family_id, is_family_head, relationship, verified,
    guardian_id, date_of_birth. Rules:
      - anyone may check themselves in;
      - a guardian may check in the people they are guardian of;
      - in a verified family, the family head and the head's spouse may check
        in everyone in that family (one phone for the whole family).
    Other family members check in only themselves; never another family.
    """
    if acting['id'] == attendee['id']:
        return True, 'self'
    if attendee.get('guardian_id') and attendee['guardian_id'] == acting['id']:
        return True, 'guardian'
    family = acting.get('family_id')
    if not family or attendee.get('family_id') != family:
        return False, 'not_family'
    if not attendee.get('verified', True) or not acting.get('verified', True):
        return False, 'not_verified'
    acting_parent = acting.get('is_family_head') or acting.get('relationship') == 'spouse'
    if not acting_parent:
        return False, 'not_authorized'
    if attendee.get('relationship') in CHILD_RELATIONSHIPS:
        return True, 'child'
    if attendee.get('relationship') == 'spouse' or attendee.get('is_family_head'):
        return True, 'spouse'
    return True, 'family'
