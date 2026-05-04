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
        domain="[('type', 'in', ['cash', 'bank']), ('company_id', '=', id)]",
        help='Journal al que se transfieren automáticamente al cierre de sesión '
             'el efectivo y los cheques de terceros recaudados. Las tarjetas NO '
             'se transfieren — quedan en su journal hasta acreditación bancaria.',
    )
