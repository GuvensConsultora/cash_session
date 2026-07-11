from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    cash_session_id = fields.Many2one(
        'cash.session', string='Sesión de caja', readonly=True,
        copy=False, index=True, ondelete='set null',
        help='Turno de caja en el que se registró este cobro/pago. Se completa '
             'solo al crear el payment, si hay una sesión abierta del usuario '
             'para la caja del journal. Es la base del arqueo por sesión '
             '(turnos intra-día exactos, sin depender de la fecha contable).',
    )

    def _cash_register_for_journal(self):
        """Caja activa a la que pertenece el journal del payment (o vacío).

        sudo: la existencia de la caja es un invariante de negocio; no debe
        depender de las record rules de visibilidad del usuario.
        """
        self.ensure_one()
        if not self.journal_id:
            return self.env['cash.register']
        return self.env['cash.register'].sudo().search([
            ('journal_ids', 'in', self.journal_id.id),
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ], limit=1)

    def _cash_open_session(self, register):
        """Sesión ABIERTA de `register` a nombre del usuario actual (o vacío)."""
        if not register:
            return self.env['cash.session']
        return self.env['cash.session'].sudo().search([
            ('cash_register_id', '=', register.id),
            ('state', '=', 'open'),
            ('responsible_id', '=', self.env.user.id),
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        """Estampa la sesión de caja abierta en cada payment de caja al crearlo.

        El candado `_check_cash_session_open` garantiza que el cajero tenga una
        sesión abierta para operar, así que en ese momento siempre la
        encontramos para vincularla. Journals que no son de caja → sin vínculo.
        """
        payments = super().create(vals_list)
        for p in payments:
            if p.cash_session_id:
                continue
            session = p._cash_open_session(p._cash_register_for_journal())
            if session:
                p.cash_session_id = session.id
        return payments

    @api.constrains('journal_id', 'payment_type', 'state')
    def _check_cash_session_outbound(self):
        """Si el journal pertenece a una caja con allow_payments_out=False,
        bloquea pagos a proveedores SOLO para cajeros (group_cash_user).

        Contaduría y tesorería (usuarios sin grupo cash_session) quedan exentos:
        necesitan pagar proveedores con cheques de terceros recibidos en caja
        sin que eso implique ser cajeros. Los managers también exentos por diseño.
        """
        for p in self:
            if p.payment_type != 'outbound':
                continue
            if not p.journal_id:
                continue
            user = self.env.user
            # Solo aplica a cajeros. Managers y usuarios fuera de cash_session exentos.
            if not user.has_group('cash_session.group_cash_user'):
                continue
            if user.has_group('cash_session.group_cash_manager'):
                continue
            register = self.env['cash.register'].search([
                ('journal_ids', 'in', p.journal_id.id),
                ('company_id', '=', p.company_id.id),
                ('active', '=', True),
            ], limit=1)
            if register and not register.allow_payments_out:
                raise UserError(_(
                    'La caja "%(c)s" NO autoriza pagos a proveedores. '
                    'No se puede registrar la OP "%(p)s" en el journal "%(j)s".',
                    c=register.display_name,
                    p=p.display_name,
                    j=p.journal_id.display_name,
                ))

    @api.constrains('journal_id', 'payment_type', 'state')
    def _check_cash_session_open(self):
        """Bloquea cobros/pagos en journals de caja si el cajero no tiene una
        sesión de caja ABIERTA a su nombre para esa caja.

        Alcance:
        - Solo journals que pertenecen a una `cash.register` activa (los de
          tesorería/banco que no son de ninguna caja quedan exentos por diseño).
        - Por defecto aplica a los usuarios cajeros (grupo `group_cash_user`).
          Tesorería (fuera de ese grupo) queda exenta, salvo que la compañía
          active `cash_enforce_payment_session_all` (entonces aplica a todos
          menos managers).
        - Los managers (`group_cash_manager`) están SIEMPRE exentos: son el rol
          de supervisión/corrección y pueden operar sin abrir turno.
        - Responsabilidad personal: la sesión abierta debe tener al usuario
          actual como responsable. No alcanza con que la caja tenga cualquier
          sesión abierta.

        Origen: incidente 26/05 — recibos cobrados sin caja abierta quedaron
        huérfanos y distorsionaron el arqueo de la sesión anterior ya cerrada.
        """
        for p in self:
            if p.state == 'canceled' or not p.journal_id:
                continue
            register = p._cash_register_for_journal()
            if not register:
                continue
            user = self.env.user
            # Managers siempre exentos (rol de supervisión/corrección).
            if user.has_group('cash_session.group_cash_manager'):
                continue
            enforce_all = p.company_id.cash_enforce_payment_session_all
            if not enforce_all and not user.has_group('cash_session.group_cash_user'):
                continue
            if not p._cash_open_session(register):
                raise UserError(_(
                    'No podés registrar este %(tipo)s en la caja "%(caja)s": '
                    'no tenés una sesión de caja abierta a tu nombre. '
                    'Abrí tu turno de caja antes de operar.',
                    tipo=_('cobro') if p.payment_type == 'inbound' else _('pago'),
                    caja=register.display_name,
                ))


class AccountBankStatement(models.Model):
    _inherit = 'account.bank.statement'

    cash_session_id = fields.Many2one(
        'cash.session', string='Sesión de caja',
        ondelete='set null', copy=False,
    )
