from odoo import _, api, fields, models


class CashSessionLine(models.Model):
    _name = 'cash.session.line'
    _description = 'Línea de arqueo de sesión de caja'
    _order = 'session_id, kind, journal_id'

    session_id = fields.Many2one(
        'cash.session', string='Sesión', required=True, ondelete='cascade',
    )
    company_id = fields.Many2one(
        related='session_id.company_id', store=True, readonly=True,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Journal', required=True,
    )
    journal_kind = fields.Selection(
        related='journal_id.cash_session_kind', store=True, readonly=True,
        string='Tipo',
    )
    kind = fields.Selection(
        [('open', 'Apertura'), ('close', 'Cierre')],
        required=True, string='Momento',
    )
    theoretical_amount = fields.Monetary(
        string='Teórico', compute='_compute_theoretical',
        currency_field='currency_id',
        help='Saldo que debería haber según el sistema. En apertura: 0 (o lo que '
             'quedó pendiente de la sesión anterior). En cierre: balance_end del '
             'statement de la sesión.',
    )
    physical_amount = fields.Monetary(
        string='Físico (recuento)', currency_field='currency_id',
    )
    difference = fields.Monetary(
        string='Diferencia', compute='_compute_difference', store=True,
        currency_field='currency_id',
        help='Físico − Teórico. Positivo = sobrante, negativo = faltante.',
    )
    note = fields.Char(string='Observación')
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True,
    )

    @api.depends('journal_id', 'session_id', 'session_id.statement_ids', 'kind')
    def _compute_theoretical(self):
        for l in self:
            stmt = l.session_id.statement_ids.filtered(
                lambda s: s.journal_id == l.journal_id
            )
            if not stmt:
                l.theoretical_amount = 0.0
                continue
            stmt = stmt[0]
            if l.kind == 'open':
                l.theoretical_amount = stmt.balance_start
            else:
                l.theoretical_amount = stmt.balance_end

    @api.depends('physical_amount', 'theoretical_amount', 'kind')
    def _compute_difference(self):
        for l in self:
            # Solo aplica al cierre (la apertura es el dato base, no hay diferencia)
            if l.kind == 'close':
                l.difference = (l.physical_amount or 0.0) - (l.theoretical_amount or 0.0)
            else:
                l.difference = 0.0
