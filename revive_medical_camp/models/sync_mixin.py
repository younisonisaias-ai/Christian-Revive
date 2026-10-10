import uuid

from odoo import fields, models


class CampSyncMixin(models.AbstractModel):
    """Records created on a phone carry the phone's own id (client_uuid), so
    an offline record that is uploaded twice is stored only once."""
    _name = 'camp.sync.mixin'
    _description = 'Camp offline-sync id'

    client_uuid = fields.Char(
        string='Device record id', index=True, copy=False, readonly=True,
        default=lambda self: str(uuid.uuid4()),
        help='Set by the device that created the record; used for offline sync.')

    _client_uuid_unique = models.Constraint(
        'UNIQUE(client_uuid)',
        'This record was already uploaded (same device record id).',
    )
