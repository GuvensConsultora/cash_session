from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPaymentSessionLock(TransactionCase):
    """Candado: cajeros no pueden cobrar/pagar en un journal de caja sin tener
    una sesión de caja ABIERTA a su nombre. Tesorería exenta salvo switch."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.cash_journal = cls.env['account.journal'].create({
            'name': 'Caja Test', 'type': 'cash', 'code': 'CJT',
            'company_id': cls.company.id,
        })
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'Banco Test', 'type': 'bank', 'code': 'BKT',
            'company_id': cls.company.id,
        })

        acct_user = cls.env.ref('account.group_account_user')
        base_user = cls.env.ref('base.group_user')
        cashier_grp = cls.env.ref('cash_session.group_cash_user')

        cls.cashier = cls.env['res.users'].create({
            'name': 'Cajero Test', 'login': 'cajero_test',
            'groups_id': [(6, 0, [base_user.id, acct_user.id, cashier_grp.id])],
        })
        cls.treasury = cls.env['res.users'].create({
            'name': 'Tesoreria Test', 'login': 'tesoreria_test',
            'groups_id': [(6, 0, [base_user.id, acct_user.id])],
        })

        cls.register = cls.env['cash.register'].create({
            'name': 'Caja Test', 'code': 'CJT', 'company_id': cls.company.id,
            'journal_ids': [(6, 0, [cls.cash_journal.id])],
            'responsible_user_ids': [(6, 0, [cls.cashier.id])],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Cliente Test'})

    def _make_payment(self, journal, user):
        pml = journal.inbound_payment_method_line_ids[:1]
        return self.env['account.payment'].with_user(user).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner.id,
            'amount': 1000.0,
            'journal_id': journal.id,
            'company_id': self.company.id,
            'payment_method_line_id': pml.id if pml else False,
        })

    def _open_session_for(self, user):
        session = self.env['cash.session'].create({
            'cash_register_id': self.register.id,
            'responsible_id': user.id,
        })
        session.action_open()
        return session

    def test_cashier_blocked_without_session(self):
        with self.assertRaises(UserError):
            self._make_payment(self.cash_journal, self.cashier)

    def test_cashier_ok_with_own_open_session(self):
        self._open_session_for(self.cashier)
        pay = self._make_payment(self.cash_journal, self.cashier)
        self.assertTrue(pay.id)

    def test_treasury_exempt_by_default(self):
        # tesorería (fuera del grupo de caja) puede operar sin sesión
        pay = self._make_payment(self.cash_journal, self.treasury)
        self.assertTrue(pay.id)

    def test_switch_enforces_treasury_too(self):
        self.company.cash_enforce_payment_session_all = True
        with self.assertRaises(UserError):
            self._make_payment(self.cash_journal, self.treasury)

    def test_non_cash_journal_unaffected(self):
        # journal de banco/tesorería: no pertenece a ninguna caja -> sin candado
        pay = self._make_payment(self.bank_journal, self.cashier)
        self.assertTrue(pay.id)

    def test_outbound_payment_also_locked(self):
        # el candado aplica también a pagos (outbound), no solo cobros
        self.register.allow_payments_out = True
        with self.assertRaises(UserError):
            self.env['account.payment'].with_user(self.cashier).create({
                'payment_type': 'outbound',
                'partner_type': 'supplier',
                'partner_id': self.partner.id,
                'amount': 500.0,
                'journal_id': self.cash_journal.id,
                'company_id': self.company.id,
                'payment_method_line_id':
                    self.cash_journal.outbound_payment_method_line_ids[:1].id or False,
            })
