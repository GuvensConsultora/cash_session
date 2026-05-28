from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    cash_difference_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de diferencias de caja',
        domain="[('deprecated', '=', False), ('company_ids', 'in', id)]",
        help='Cuenta donde se imputan las diferencias (faltantes o sobrantes) '
             'al cerrar las sesiones de caja con arqueo distinto al teórico.',
    )
    cash_central_journal_id = fields.Many2one(
        'account.journal',
        string='Caja central (destino de transferencia al cierre)',
        domain="[('type', 'in', ['cash', 'bank'])]",
        help='Journal al que se transfieren automáticamente al cierre de sesión '
             'el efectivo y los cheques de terceros. Puede pertenecer a OTRA '
             'compañía: en ese caso, se generan dos asientos espejo (uno en cada '
             'compañía) usando las cuentas intercompany configuradas — RT 9 '
             'FACPCE: saldos con sociedades vinculadas separados activo/pasivo.',
    )
    cash_intercompany_receivable_id = fields.Many2one(
        'account.account',
        string='Cta. cte. intercompany — a cobrar',
        domain="[('deprecated', '=', False),"
               " ('company_ids', 'in', id),"
               " ('account_type', '=', 'asset_receivable')]",
        help='Cuenta a cobrar a la compañía contraparte cuando esta compañía '
             'transfiere caja a la caja central de la otra. Refleja el crédito '
             'contra la sociedad vinculada.',
    )
    cash_intercompany_payable_id = fields.Many2one(
        'account.account',
        string='Cta. cte. intercompany — a pagar',
        domain="[('deprecated', '=', False),"
               " ('company_ids', 'in', id),"
               " ('account_type', '=', 'liability_payable')]",
        help='Cuenta a pagar a la compañía contraparte cuando la caja central '
             'de esta compañía recibe una transferencia de la otra. Refleja la '
             'deuda con la sociedad vinculada.',
    )
    cash_enforce_payment_session_all = fields.Boolean(
        string='Exigir caja abierta a todos los usuarios',
        default=False,
        help='Por defecto, el bloqueo de cobros/pagos sin sesión de caja abierta '
             'aplica solo a los usuarios cajeros (grupo "Cash Session — Usuario"); '
             'tesorería queda exenta. Si se activa, el bloqueo aplica a TODOS los '
             'usuarios que operen un journal de caja, incluida tesorería.',
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cash_difference_account_id = fields.Many2one(
        related='company_id.cash_difference_account_id',
        readonly=False,
    )
    cash_central_journal_id = fields.Many2one(
        related='company_id.cash_central_journal_id',
        readonly=False,
    )
    cash_intercompany_receivable_id = fields.Many2one(
        related='company_id.cash_intercompany_receivable_id',
        readonly=False,
    )
    cash_intercompany_payable_id = fields.Many2one(
        related='company_id.cash_intercompany_payable_id',
        readonly=False,
    )
    cash_enforce_payment_session_all = fields.Boolean(
        related='company_id.cash_enforce_payment_session_all',
        readonly=False,
    )
