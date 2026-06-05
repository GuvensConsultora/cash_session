from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    cash_session_kind = fields.Selection(
        [('cash', 'Efectivo'),
         ('third_party_check', 'Cheques de terceros'),
         ('card', 'Tarjeta'),
         ('none', 'No aplica')],
        string='Tipo en caja',
        default='none',
        help='Define cómo se trata este journal en una sesión de caja:\n'
             '- Efectivo: se arquea físicamente y se transfiere a caja central al cierre.\n'
             '- Cheques de terceros: se recuenta e informa en el cierre, pero NO se transfiere (queda en su journal).\n'
             '- Tarjeta: se recuenta pero NO se transfiere (queda hasta acreditación).\n'
             '- No aplica: se ignora si llegara a estar entre los journals de una caja.',
    )
