"""Validated report scopes and inclusive calendar-date boundaries."""
from datetime import date, datetime, time, timedelta
import pytz

SECTIONS = {'membership', 'families', 'ministry', 'worship', 'giving', 'care', 'visitors'}
JOBS = {'membership': ('members',), 'families': ('families',),
        'ministry': ('groups', 'assignments'), 'worship': ('services', 'attendance'),
        'giving': ('donations', 'pledges'), 'care': ('prayers', 'notes'),
        'visitors': ('visitors',)}
MAX_SELECTED_MEMBERS = 500


def member_filter(job, member_ids):
    """Extra domain limiting a section to the chosen members."""
    if not member_ids:
        return []
    ids = list(member_ids)
    return {
        'members': [('id', 'in', ids)],
        'families': [('member_ids', 'in', ids)],
        'groups': ['|', ('member_ids', 'in', ids), ('leader_id', 'in', ids)],
        'assignments': [('member_id', 'in', ids)],
        'services': [('attendance_ids.member_id', 'in', ids)],
        'attendance': [('member_id', 'in', ids)],
        'donations': [('partner_id', 'in', ids)],
        'pledges': [('member_id', 'in', ids)],
        'prayers': [('partner_id', 'in', ids)],
        'notes': [('member_id', 'in', ids)],
        'visitors': [('id', 'in', ids)],
    }.get(job, [])

def validate(options):
    options = dict(options or {})
    selected = options.get('sections', sorted(SECTIONS))
    if not isinstance(selected, list) or not selected or any(s not in SECTIONS for s in selected):
        raise ValueError('Choose valid report sections.')
    start, end = options.get('date_from'), options.get('date_to')
    if bool(start) != bool(end):
        raise ValueError('Both start and end dates are required.')
    if start:
        start, end = date.fromisoformat(start), date.fromisoformat(end)
        if start > end:
            raise ValueError('The end date must not precede the start date.')
    for flag in ('detailed', 'include_sensitive'):
        if flag in options and not isinstance(options[flag], bool):
            raise ValueError('Report flags must be true or false.')
    detailed = options.get('detailed', False)
    sensitive = detailed and options.get('include_sensitive', False) and 'care' in selected
    # Optional: report on these members only (empty = whole church).
    member_ids = options.get('member_ids') or []
    if not isinstance(member_ids, list) or len(member_ids) > MAX_SELECTED_MEMBERS or any(
            isinstance(i, bool) or not isinstance(i, int) or i <= 0 for i in member_ids):
        raise ValueError('Choose up to %d valid members.' % MAX_SELECTED_MEMBERS)
    return {'sections': list(dict.fromkeys(selected)), 'start': start, 'end': end,
            'detailed': detailed, 'sensitive': sensitive,
            'member_ids': sorted(set(member_ids))}

def date_domain(field, options, timezone='UTC', datetime_field=True):
    if not options['start']:
        return []
    if not datetime_field:
        return [(field, '>=', options['start'].isoformat()),
                (field, '<=', options['end'].isoformat())]
    tz = pytz.timezone(timezone or 'UTC')
    def utc(day):
        return tz.localize(datetime.combine(day, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
    return [(field, '>=', utc(options['start'])),
            (field, '<', utc(options['end'] + timedelta(days=1)))]

def jobs(options):
    if not options['detailed']:
        return []
    return [job for section in options['sections'] for job in JOBS[section]
            if job not in ('prayers', 'notes') or options['sensitive']]
