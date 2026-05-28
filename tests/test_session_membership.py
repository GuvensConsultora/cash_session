from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSessionMembership(TransactionCase):
    """Pertenencia por sesión (vínculo) para soportar varios turnos por día.

    Se prueba a nivel lógica (estampado de cash_session_id al crear + bifurcación
    del dominio vínculo/fecha), sin depender del posteo contable completo, que se
    valida end-to-end en la instancia de testing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.cash_journal = cls.env['account.journal'].create({
            'name': 'Caja Test', 'type': 'cash', 'code': 'CJT',
            'company_id': cls.company.id,
        })
        cls.cashier = cls.env['res.users'].create({
            'name': 'Cajero Test', 'login': 'cajero_memb',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_user').id,
                cls.env.ref('cash_session.group_cash_user').id,
            ])],
        })
        cls.treasury = cls.env['res.users'].create({
            'name': 'Tesoreria Test', 'login': 'tesoreria_memb',
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('account.group_account_user').id,
            ])],
        })
        cls.register = cls.env['cash.register'].create({
            'name': 'Caja Test', 'code': 'CJT', 'company_id': cls.company.id,
            'journal_ids': [(6, 0, [cls.cash_journal.id])],
            'responsible_user_ids': [(6, 0, [cls.cashier.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Test'})

    def _open_session(self, user):
        session = self.env['cash.session'].create({
            'cash_register_id': self.register.id,
            'responsible_id': user.id,
        })
        session.action_open()
        return session

    def _make_payment(self, user):
        return self.env['account.payment'].with_user(user).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 1000.0,
            'journal_id': self.cash_journal.id,
            'company_id': self.company.id,
            'payment_method_line_id':
                self.cash_journal.inbound_payment_method_line_ids[:1].id or False,
        })

    def test_new_session_is_link_based(self):
        session = self._open_session(self.cashier)
        self.assertTrue(session.membership_by_link)

    def test_payment_stamped_to_open_session(self):
        session = self._open_session(self.cashier)
        pay = self._make_payment(self.cashier)
        self.assertEqual(pay.cash_session_id, session)

    def test_two_turnos_same_day_distinct_links(self):
        # Turno A
        sA = self._open_session(self.cashier)
        pA = self._make_payment(self.cashier)
        # Cierre forzado de A para liberar la caja (sin el flujo contable completo)
        sA.sudo().write({'state': 'closed', 'date_close': fields.Datetime.now()})
        # Turno B, mismo día, misma caja
        sB = self._open_session(self.cashier)
        pB = self._make_payment(self.cashier)
        self.assertNotEqual(sA, sB)
        self.assertEqual(pA.cash_session_id, sA)
        self.assertEqual(pB.cash_session_id, sB)
        # Cada turno reclama solo su propio cobro (sin contaminación intra-día)
        self.assertIn(('cash_session_id', '=', sA.id), sA._session_payment_domain())
        self.assertIn(('cash_session_id', '=', sB.id), sB._session_payment_domain())

    def test_legacy_session_domain_uses_date(self):
        session = self._open_session(self.cashier)
        session.sudo().write({'membership_by_link': False})
        dom = session._session_payment_domain()
        self.assertFalse(any(t[0] == 'cash_session_id' for t in dom))
        self.assertTrue(any(t[0] == 'date' for t in dom))

    def test_payment_without_session_not_stamped(self):
        # Tesorería (exenta del candado) crea sin sesión -> queda sin vínculo
        pay = self._make_payment(self.treasury)
        self.assertFalse(pay.cash_session_id)
