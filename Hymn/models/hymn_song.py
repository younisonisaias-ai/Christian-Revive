import json
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HymnSong(models.Model):
    _name = 'hymn.song'
    _description = 'Hymn / Song'
    _order = 'collection_id, number, id'
    _inherit = ['mail.thread']

    # ── Core Fields ──
    name = fields.Char(string='Title (Roman/English)', required=True, tracking=True,
                       help='Roman transliteration or English title')
    title_urdu = fields.Char(string='Title (Urdu/Original)', tracking=True,
                             help='Title in original script (Urdu, Punjabi, Arabic)')
    number = fields.Integer(string='Song Number', required=True, tracking=True,
                            help='Number within the collection')
    collection_id = fields.Many2one('hymn.collection', string='Collection',
                                    required=True, ondelete='cascade', tracking=True)
    category_id = fields.Many2one('hymn.category', string='Category',
                                  tracking=True)
    author = fields.Char(string='Author / Composer')
    tune = fields.Char(string='Tune / Melody')
    scripture = fields.Char(string='Scripture Reference',
                            help='e.g. متی ۷:۷ or Matthew 7:7')
    tags = fields.Char(string='Tags',
                       help='Comma-separated tags for search, e.g. prayer, dua, ilteja')

    # ── Language ──
    language = fields.Selection(related='collection_id.language',
                                string='Language', store=True, readonly=True)

    # ── Chorus ──
    chorus = fields.Text(string='Chorus (Original Script)',
                         help='Chorus text in Urdu or original language')
    chorus_roman = fields.Text(string='Chorus (Roman)',
                               help='Roman transliteration of the chorus')

    # ── Publishing ──
    is_published = fields.Boolean(string='Published', default=True, tracking=True)
    is_featured = fields.Boolean(string='Featured', default=False,
                                 help='Show in featured/highlighted section')

    # ── Metadata ──
    sequence = fields.Integer(string='Display Order', default=10)
    image = fields.Binary(string='Song Image', attachment=True)

    # ── Relationships ──
    verse_ids = fields.One2many('hymn.verse', 'song_id', string='Verses',
                                copy=True)
    verse_count = fields.Integer(string='Verses', compute='_compute_verse_count')

    # ── Display ──
    display_name_full = fields.Char(compute='_compute_display_name_full',
                                     string='Full Title')
    collection_name = fields.Char(related='collection_id.name',
                                   string='Collection Name', store=True)
    category_code = fields.Char(related='category_id.code',
                                 string='Category Code', store=True)

    _sql_constraints = [
        ('number_collection_unique', 'UNIQUE(number, collection_id)',
         'Song number must be unique within a collection!'),
    ]

    @api.depends('verse_ids')
    def _compute_verse_count(self):
        for rec in self:
            rec.verse_count = len(rec.verse_ids)

    @api.depends('number', 'name', 'title_urdu')
    def _compute_display_name_full(self):
        for rec in self:
            parts = [f'#{rec.number}']
            if rec.title_urdu:
                parts.append(str(rec.title_urdu))
            if rec.name:
                parts.append(str(rec.name))
            rec.display_name_full = ' - '.join(parts)

    @api.constrains('number')
    def _check_number(self):
        for rec in self:
            if rec.number < 1:
                raise ValidationError('Song number must be 1 or greater.')

    # ── API for Flutter ──

    def _songs_to_list(self, songs):
        """Convert a songs recordset to dicts, fetching all verses in a single query."""
        if not songs:
            return []
        all_verses = self.env['hymn.verse'].search_read(
            [('song_id', 'in', songs.ids)],
            fields=['song_id', 'verse_number', 'text', 'roman', 'sequence'],
            order='sequence asc',
        )
        verses_by_song = {}
        for v in all_verses:
            sid = v['song_id'][0]
            verses_by_song.setdefault(sid, []).append(v)

        result = []
        for s in songs:
            raw = verses_by_song.get(s.id, [])
            verses = [
                {'verse': v['verse_number'], 'text': v['text'] or '', 'roman': v['roman'] or ''}
                for v in raw
            ]
            result.append({
                'id':          s.id,
                'number':      s.number,
                'title':       s.name,
                'titleUrdu':   s.title_urdu or '',
                'author':      s.author or '',
                'category':    s.category_id.code if s.category_id else 'general',
                'tune':        s.tune or '',
                'scripture':   s.scripture or '',
                'tags':        [t.strip() for t in (s.tags or '').split(',') if t.strip()],
                'chorus':      s.chorus or None,
                'chorusRoman': s.chorus_roman or None,
                'verses':      verses,
                'is_featured': s.is_featured,
            })
        return result

    @api.model
    def app_fetch_songs(self, *args, **kwargs):
        # _callKw sends ([], 'hymns', 200, 0) — skip the empty [] record IDs
        clean = [a for a in args if a != []]
        collection_code = clean[0] if clean else None
        limit  = clean[1] if len(clean) > 1 else 200
        offset = clean[2] if len(clean) > 2 else 0
        """Fetch all published songs for a collection — used by the Flutter app."""
        collection = self.env['hymn.collection'].search([
            ('code', '=', collection_code),
            ('is_published', '=', True),
        ], limit=1)
        if not collection:
            return []
        songs = self.search([
            ('collection_id', '=', collection.id),
            ('is_published', '=', True),
        ], order='number asc', limit=limit, offset=offset)
        return self._songs_to_list(songs)

    @api.model
    def app_search_songs(self, collection_code=None, query='', category='', limit=50):
        """Search songs by title, author, tags, or lyrics content."""
        collection = self.env['hymn.collection'].search([
            ('code', '=', collection_code),
        ], limit=1)
        if not collection:
            return []

        domain = [
            ('collection_id', '=', collection.id),
            ('is_published', '=', True),
        ]

        if category:
            cat = self.env['hymn.category'].search([('code', '=', category)], limit=1)
            if cat:
                domain.append(('category_id', '=', cat.id))

        if query:
            domain = [
                ('collection_id', '=', collection.id),
                ('is_published', '=', True),
                '|', '|', '|', '|',
                ('name', 'ilike', query),
                ('title_urdu', 'ilike', query),
                ('author', 'ilike', query),
                ('tags', 'ilike', query),
                ('verse_ids.roman', 'ilike', query),
            ]
            if category:
                cat = self.env['hymn.category'].search([('code', '=', category)], limit=1)
                if cat:
                    domain.append(('category_id', '=', cat.id))

        songs = self.search(domain, order='number asc', limit=limit)
        return self._songs_to_list(songs)

    # ── Bulk Import ──
    @api.model
    def import_from_json(self, collection_code, json_data):
        """
        Import songs from JSON array (same format as geet_zaboor.json).
        Call from Odoo shell or action button.
        """
        collection = self.env['hymn.collection'].search([
            ('code', '=', collection_code)
        ], limit=1)
        if not collection:
            raise ValidationError(f'Collection with code "{collection_code}" not found.')

        if isinstance(json_data, str):
            json_data = json.loads(json_data)

        created = 0
        for item in json_data:
            # Find or skip category
            cat = False
            cat_code = item.get('category', 'general')
            cat_rec = self.env['hymn.category'].search([('code', '=', cat_code)], limit=1)
            if cat_rec:
                cat = cat_rec.id

            # Build verse lines
            verse_lines = []
            for v in item.get('verses', []):
                verse_lines.append((0, 0, {
                    'verse_number': v.get('verse', 1),
                    'text': v.get('text', ''),
                    'roman': v.get('roman', ''),
                    'sequence': v.get('verse', 1) * 10,
                }))

            # Check if song already exists
            existing = self.search([
                ('collection_id', '=', collection.id),
                ('number', '=', item.get('number', 0)),
            ], limit=1)
            if existing:
                continue

            self.create({
                'name': item.get('title', ''),
                'title_urdu': item.get('titleUrdu', ''),
                'number': item.get('number', 0),
                'collection_id': collection.id,
                'category_id': cat,
                'author': item.get('author', ''),
                'tune': item.get('tune', ''),
                'scripture': item.get('scripture', ''),
                'tags': ','.join(item.get('tags', [])),
                'chorus': item.get('chorus') or False,
                'chorus_roman': item.get('chorusRoman') or False,
                'is_published': True,
                'verse_ids': verse_lines,
            })
            created += 1

        return {'created': created, 'total': len(json_data)}
