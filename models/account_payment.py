from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    @api.constrains('journal_id', 'payment_type', 'state')
    def _check_cash_session_outbound(self):
        """Si el journal pertenece a una caja con allow_payments_out=False,
        no se puede crear/postear un payment outbound (pago a proveedor) desde acá."""
        for p in self:
            if p.payment_type != 'outbound':
                continue
            if not p.journal_id:
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


class AccountBankStatement(models.Model):
    _inherit = 'account.bank.statement'

    cash_session_id = fields.Many2one(
        'cash.session', string='Sesión de caja',
        ondelete='set null', copy=False,
    )
