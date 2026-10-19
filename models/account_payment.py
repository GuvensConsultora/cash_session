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

        Un journal puede estar en varias cajas (las tarjetas y el banco son
        los mismos para Facturación y Repuestos). En ese caso el cobro es de
        la caja donde el usuario actual tiene su turno abierto o en cierre;
        si no tiene turno en ninguna, la primera, como antes.

        Caso 2026-10-17: las tarjetas estaban sólo en Facturación y el
        cajero de Repuestos, con su turno abierto, no podía cobrar con débito.

        sudo: la existencia de la caja es un invariante de negocio; no debe
        depender de las record rules de visibilidad del usuario.
        """
        self.ensure_one()
        if not self.journal_id:
            return self.env['cash.register']
        registers = self.env['cash.register'].sudo().search([
            ('journal_ids', 'in', self.journal_id.id),
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ])
        if len(registers) > 1:
            del_turno = self.env['cash.session'].sudo().search([
                ('cash_register_id', 'in', registers.ids),
                ('state', 'in', ('open', 'closing')),
                ('responsible_id', '=', self.env.user.id),
            ], limit=1).cash_register_id
            if del_turno:
                return del_turno
        return registers[:1]

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

    def _cash_session_del_usuario(self, register, estados=('open', 'closing')):
        """Sesión del cajero actual para `register`, abierta o en cierre.

        Se acepta `closing` a propósito: mientras el cajero cuenta la caja el
        turno sigue siendo suyo, y la plata que se confirma en ese momento es
        de ese turno.
        """
        if not register:
            return self.env['cash.session']
        return self.env['cash.session'].sudo().search([
            ('cash_register_id', '=', register.id),
            ('state', 'in', list(estados)),
            ('responsible_id', '=', self.env.user.id),
        ], limit=1)

    def _cash_resync_session(self):
        """Reasigna la caja cuando el pago se CONFIRMA en un turno distinto de
        aquel en que se creó.

        `create()` estampa la sesión abierta del momento, y el arqueo arma por
        ese vínculo. Pero un pago puede nacer en un turno y confirmarse en otro:
        el recibo se arma un día, queda en borrador porque no se cobró, y se
        confirma días después cuando entra la plata. Mientras está en borrador
        no cuenta para ningún arqueo; al confirmarlo cuenta para el turno VIEJO,
        que a esa altura suele estar cerrado. El efectivo queda colgado en una
        caja que ya nadie cuenta y falta en la que el cajero tiene en la mano.

        Caso 2026-08-27 (MADERAS SSAP, $2.584.000): el recibo se armó el 22, no
        se cobró y quedó en borrador; el efectivo entró el 27. Al confirmarlo,
        el pago se sumó a la caja del 22 —cerrada, y cerrada sin línea de
        efectivo— y la del 27 no lo veía.

        Sólo actúa si la sesión estampada YA NO está abierta ni en cierre. Si
        quien confirma no es cajero y no tiene turno propio, no se toca nada:
        es preferible dejar el vínculo viejo, visible, que inventar uno.
        """
        for p in self:
            if p.state in ('draft', 'canceled', 'rejected'):
                continue
            register = p._cash_register_for_journal()
            if not register:
                continue
            vieja = p.cash_session_id
            if vieja and vieja.state in ('open', 'closing'):
                continue
            nueva = p._cash_session_del_usuario(register)
            if not nueva or nueva == vieja:
                continue
            p.sudo().write({'cash_session_id': nueva.id})
            p.message_post(body=_(
                'Sesión de caja reasignada de %(vieja)s a %(nueva)s: el pago se '
                'creó en un turno y se confirmó en otro. El arqueo arma por este '
                'vínculo, así que sin el cambio el importe quedaba en la caja '
                'vieja y faltaba en la del turno en que realmente se cobró.',
                vieja=vieja.display_name if vieja else _('(ninguna)'),
                nueva=nueva.display_name,
            ))

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
            register = p._cash_register_for_journal()
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
            if p.state in ('canceled', 'rejected') or not p.journal_id:
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


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        """Al postear el asiento de un pago de caja, revisar su turno.

        Es el único momento en que el pago pasa a contar para un arqueo, así
        que es donde corresponde verificar que el turno estampado siga siendo
        el correcto. Ver `account.payment._cash_resync_session`.
        """
        res = super().action_post()
        pagos = self.mapped('origin_payment_id')
        if pagos:
            pagos._cash_resync_session()
        return res


class AccountBankStatement(models.Model):
    _inherit = 'account.bank.statement'

    cash_session_id = fields.Many2one(
        'cash.session', string='Sesión de caja',
        ondelete='set null', copy=False,
    )
