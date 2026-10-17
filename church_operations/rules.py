"""Small deterministic rules, shared by RPC validation and regression tests."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re

KINDS = ('follow_up', 'visitor', 'verification', 'pledge', 'absence', 'general')
STAGES = ('new', 'contacted', 'returning', 'joined', 'not_interested')

def positive_id(raw, optional=False):
    if optional and raw in (None, False, ''):
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError('Choose a valid record.')
    return raw

def money(raw, zero=False):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Enter a valid amount.')
    if not value.is_finite() or value < 0 or (not zero and value == 0):
        raise ValueError('Enter a positive, finite amount.')
    rounded = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if not zero and rounded == 0:
        raise ValueError('The amount must be at least 0.01.')
    return rounded

def refund_net(amount, refunded, state):
    gross, returned = money(amount, zero=True), money(refunded, zero=True)
    if returned > gross:
        raise ValueError('Refunds cannot exceed the original donation.')
    return Decimal(0) if state == 'refunded' else gross - returned

def contact_keys(name='', email='', phone=''):
    return (' '.join((name or '').casefold().split()),
            (email or '').strip().casefold(), re.sub(r'\D', '', phone or ''))

def request_hash(action, payload):
    body = {k: v for k, v in payload.items() if k != 'request_key'}
    return hashlib.sha256((action + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()

def page_args(payload):
    after = payload.get('after_id', 0)
    limit = payload.get('limit', 40)
    if isinstance(after, bool) or not isinstance(after, int) or after < 0:
        raise ValueError('Invalid page cursor.')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Choose a page size between 1 and 100.')
    return after, limit

def request_key(payload):
    key = payload.get('request_key', '')
    if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', key):
        raise ValueError('A save identifier is required. Reopen the form and retry.')
    return key
