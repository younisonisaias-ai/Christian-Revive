import base64

from odoo.tests import TransactionCase, tagged

# Smallest valid PNG header plus padding: enough for the type check.
PNG = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'\0' * 64).decode()


@tagged('post_install', '-at_install')
class TestCellGroupChat(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Partner = env['res.partner']
        cls.leader = Partner.create({'name': 'Leader Gill', 'is_member': True})
        cls.member = Partner.create({'name': 'Member Masih', 'is_member': True})
        cls.outsider = Partner.create({'name': 'Not In Group', 'is_member': True})
        cls.group = env['cell.group'].create({
            'name': 'East Cell', 'leader_id': cls.leader.id, 'member_ids': [(6, 0, [cls.member.id])]})
        cls.pastor = env['hr.employee'].create({
            'name': 'Pastor Senior', 'staff_role': 'pastor', 'is_senior_pastor': True,
            'is_app_active': True, 'app_email': 'senior@example.invalid', 'app_pin': '1234'})
        Session = env['church.app.session']
        cls.tokens = {
            cls.leader.id: Session._issue('member', partner=cls.leader),
            cls.member.id: Session._issue('member', partner=cls.member),
            cls.outsider.id: Session._issue('member', partner=cls.outsider),
        }
        cls.pastor_token = Session._issue('staff', employee=cls.pastor)

    def as_member(self, partner):
        return self.env['cell.group'].with_context(app_session_token=self.tokens[partner.id])

    def send(self, partner, body='', **kw):
        return self.as_member(partner).app_chat_send(
            self.group.id, body, requester_partner_id=partner.id, **kw)

    def read(self, partner, **kw):
        return self.as_member(partner).app_chat_messages(
            self.group.id, requester_partner_id=partner.id, **kw)

    def test_members_chat_and_outsiders_cannot(self):
        self.assertTrue(self.send(self.member, 'Hello group')['success'])
        result = self.read(self.leader)
        self.assertEqual([m['body'] for m in result['messages']], ['Hello group'])
        self.assertFalse(result['messages'][0]['mine'])
        self.assertTrue(result['can_moderate'])
        self.assertFalse(self.read(self.outsider)['success'])
        self.assertFalse(self.send(self.outsider, 'Hi')['success'])

    def test_pastor_reads_and_posts(self):
        self.send(self.member, 'Prayer tonight?')
        Group = self.env['cell.group'].with_context(app_staff_session_token=self.pastor_token)
        result = Group.app_chat_messages(self.group.id, requester_staff_id=self.pastor.id)
        self.assertTrue(result['success'])
        sent = Group.app_chat_send(self.group.id, 'Yes, 7 PM', requester_staff_id=self.pastor.id)
        self.assertTrue(sent['message']['author_is_staff'])

    def test_photo_checked(self):
        self.assertTrue(self.send(self.member, image=PNG)['message']['has_image'])
        bad = base64.b64encode(b'not a picture at all').decode()
        self.assertFalse(self.send(self.member, image=bad)['success'])
        self.assertFalse(self.send(self.member, '   ')['success'])

    def test_resend_with_same_key_is_not_duplicated(self):
        first = self.send(self.member, 'Once', client_key='k1')
        again = self.send(self.member, 'Once', client_key='k1')
        self.assertEqual(first['message']['id'], again['message']['id'])
        self.assertEqual(len(self.read(self.leader)['messages']), 1)

    def test_leader_silences_and_deletes(self):
        message = self.send(self.member, 'Off topic')['message']
        Leader = self.as_member(self.leader)
        self.assertTrue(Leader.app_chat_set_silenced(
            self.group.id, self.member.id, True, requester_partner_id=self.leader.id)['success'])
        self.assertFalse(self.send(self.member, 'Again')['success'])
        self.assertFalse(Leader.app_chat_set_silenced(
            self.group.id, self.leader.id, True, requester_partner_id=self.leader.id)['success'])
        self.assertTrue(Leader.app_chat_delete(message['id'], requester_partner_id=self.leader.id)['success'])
        shown = self.read(self.member)['messages'][0]
        self.assertTrue(shown['deleted'])
        self.assertEqual(shown['body'], '')

    def test_members_delete_only_their_own(self):
        mine = self.send(self.leader, 'From the leader')['message']
        result = self.as_member(self.member).app_chat_delete(mine['id'], requester_partner_id=self.member.id)
        self.assertFalse(result['success'])

    def test_unread_count_on_group_list(self):
        self.send(self.leader, 'One')
        self.send(self.leader, 'Two')
        groups = self.as_member(self.member).app_get_cell_groups(requester_partner_id=self.member.id)
        self.assertEqual(groups['groups'][0]['chat_unread'], 2)
        self.read(self.member)
        groups = self.as_member(self.member).app_get_cell_groups(requester_partner_id=self.member.id)
        self.assertEqual(groups['groups'][0]['chat_unread'], 0)
