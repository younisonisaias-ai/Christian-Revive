"""church_management 1.3.0 — give existing members a member number.

New members get one automatically; this numbers everyone who was already a
member, oldest first, so the earliest members get the lowest numbers.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    members = env['res.partner'].with_context(active_test=False).search(
        [('is_member', '=', True), ('member_number', '=', False)],
        order='create_date asc, id asc')
    members._assign_member_numbers()
    _logger.info('church_management 1.3.0: assigned member numbers to %s member(s)', len(members))
