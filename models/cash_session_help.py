from odoo import fields, models


class CashSessionHelp(models.Model):
    _name = 'cash.session.help'
    _description = 'Ayuda — FAQ y guías de Caja'
    _order = 'kind, sequence, id'

    name = fields.Char(string='Pregunta / Tema', required=True, translate=True)
    kind = fields.Selection(
        [('faq', 'Pregunta frecuente'),
         ('howto', 'Cómo funciona el sistema')],
        string='Tipo', required=True, default='faq',
    )
    sequence = fields.Integer(string='Orden', default=10)
    short_answer = fields.Char(
        string='Resumen',
        help='Una línea con la respuesta corta.',
    )
    content = fields.Html(
        string='Contenido', sanitize=True, translate=True,
        help='Explicación detallada con formato.',
    )
    active = fields.Boolean(default=True)
