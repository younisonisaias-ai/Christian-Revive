"""Expense and budget rules with no Odoo imports, so they can be unit tested
on any machine and shared by every RPC entry point."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

CURRENCIES = ('PKR', 'USD', 'GBP', 'EUR')
METHODS = ('cash', 'bank', 'cheque', 'mobile', 'other')
STATES = ('draft', 'submitted', 'approved', 'paid', 'rejected', 'reversed')
DEFAULT_APPROVAL_LIMIT = Decimal('50000')
# Roles that may record spending. Pastors submit only; finance and Admin run it.
SUBMITTERS = ('admin', 'finance_officer', 'pastor')
MANAGERS = ('admin', 'finance_officer')
MAX_RECEIPT_BYTES = 5 * 1024 * 1024


def money(raw, zero=False):
    """A positive amount rounded to 2 places; never rounds a bad value to 0."""
    if isinstance(raw, bool):
        raise ValueError('Enter a valid amount.')
    try:
        value = Decimal(str(raw).replace(',', '').strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Enter a valid amount.')
    if not value.is_finite() or value < 0 or (not zero and value == 0):
        raise ValueError('Enter a positive amount.')
    rounded = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if not zero and rounded == 0:
        raise ValueError('The amount must be at least 0.01.')
    if rounded >= Decimal('1000000000000'):
        raise ValueError('The amount is too large.')
    return rounded


def pkr_amount(amount, currency, amount_pkr=None):
    """PKR value used for budgets and approval limits.

    Foreign-currency spending needs the PKR actually paid: the church's own
    bank figure, never a guessed exchange rate."""
    if currency not in CURRENCIES:
        raise ValueError('Choose a currency.')
    value = money(amount)
    if currency == 'PKR':
        return value
    if amount_pkr in (None, '', False):
        raise ValueError('Enter the amount paid in PKR for foreign-currency spending.')
    return money(amount_pkr)


def can_view_all(role):
    return role in MANAGERS


def can_edit(role, staff_id, expense):
    """Only drafts and rejected expenses change; the submitter or finance."""
    if expense['state'] not in ('draft', 'rejected'):
        return False
    return expense['submitted_by'] == staff_id or role in MANAGERS


def approval_problem(role, staff_id, expense, limit):
    """None when this person may approve or reject, else the reason."""
    if expense['state'] != 'submitted':
        return 'Only submitted expenses can be approved or rejected.'
    if role not in MANAGERS:
        return 'Only Finance or an Admin can approve spending.'
    if expense['submitted_by'] == staff_id:
        return 'You cannot approve your own expense. Ask another approver.'
    if role == 'finance_officer' and Decimal(str(expense['amount_pkr'])) > Decimal(str(limit)):
        return 'This amount is above the Finance approval limit. An Admin must approve it.'
    return None


def payment_problem(role, expense):
    if role not in MANAGERS:
        return 'Only Finance or an Admin can mark spending as paid.'
    if expense['state'] != 'approved':
        return 'Only approved expenses can be marked as paid.'
    return None


def reversal_problem(role, expense):
    if role != 'admin':
        return 'Only an Admin can reverse a paid expense.'
    if expense['state'] != 'paid':
        return 'Only paid expenses can be reversed.'
    return None


def budget_status(planned, actual):
    """Usage of one budget line: ok / warning (80%+) / over (100%+)."""
    planned, actual = Decimal(str(planned or 0)), Decimal(str(actual or 0))
    if planned <= 0:
        return {'percent': None, 'level': 'over' if actual > 0 else 'ok',
                'remaining': float(-actual)}
    percent = (actual * 100 / planned).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    level = 'over' if percent >= 100 else 'warning' if percent >= 80 else 'ok'
    return {'percent': float(percent), 'level': level, 'remaining': float(planned - actual)}


def clean_text(raw, limit, required_message=None):
    value = ' '.join(str(raw or '').split())[:limit]
    if required_message and not value:
        raise ValueError(required_message)
    return value


def check_receipt(data_b64, filename):
    """Light checks on an uploaded receipt photo or PDF (base64 text)."""
    if not data_b64:
        return None
    if not isinstance(data_b64, str) or not re.fullmatch(r'[A-Za-z0-9+/=\s]+', data_b64):
        raise ValueError('The receipt file could not be read.')
    if len(data_b64) * 3 // 4 > MAX_RECEIPT_BYTES:
        raise ValueError('The receipt is larger than 5 MB. Take a smaller photo.')
    name = str(filename or 'receipt.jpg')
    if not re.search(r'\.(jpe?g|png|webp|heic|pdf)$', name, re.I):
        raise ValueError('Attach a photo (JPG, PNG) or a PDF receipt.')
    return re.sub(r'[^\w.\- ]', '_', name)[:120]


def request_key(raw):
    if raw in (None, ''):
        return None
    if not isinstance(raw, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,100}', raw):
        raise ValueError('Invalid save identifier. Reopen the form and retry.')
    return raw
