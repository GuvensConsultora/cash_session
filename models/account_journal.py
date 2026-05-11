from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    cash_session_kind = fields.Selection(
        [('cash', 'Efectivo'),
         ('third_party_check', 'Cheques de terceros'),
         ('card', 'Tarjeta'),
         ('bank', 'Transferencia bancaria'),
         ('none', 'No aplica')],
        string='Tipo en caja',
        default='none',
        help='Define cómo se trata este journal en una sesión de caja:\n'
             '- Efectivo: se arquea físicamente y se transfiere a caja central al cierre.\n'
             '- Cheques de terceros: quedan en cartera de la compañía, no se transfieren.\n'
             '- Tarjeta: se recuenta pero NO se transfiere (queda hasta acreditación).\n'
             '- Transferencia bancaria: no se rinde físicamente; el cajero solo verifica '
             'el comprobante. Aparece en la minuta como detalle informativo.\n'
             '- No aplica: se ignora si llegara a estar entre los journals de una caja.',
    )
