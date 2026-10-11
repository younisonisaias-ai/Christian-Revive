"""Existing referrals get a confirmation code for the QR on their letter."""
import secrets


def migrate(cr, version):
    cr.execute("SELECT id FROM camp_referral WHERE confirm_code IS NULL")
    for (rid,) in cr.fetchall():
        cr.execute("UPDATE camp_referral SET confirm_code = %s WHERE id = %s", (secrets.token_urlsafe(24), rid))
