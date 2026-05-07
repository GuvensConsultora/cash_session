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
        help='Saldo que debería haber según el sistema. En apertura: balance '
             'start del statement (lo que se cargó como arqueo inicial). En cierre: '
             'balance_start + suma de account.payment posteados en el journal '
             'durante la sesión (entradas - salidas).',
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

    @api.depends(
        'journal_id', 'session_id', 'session_id.statement_ids',
        'session_id.date_open', 'session_id.date_close', 'session_id.state',
        'kind',
    )
    def _compute_theoretical(self):
        """Calcula el saldo teórico de la línea.

        En apertura: el balance_start del statement (arqueo físico inicial).
        En cierre: balance_start + entradas (account.payment inbound) − salidas
        (account.payment outbound) posteados en el journal durante la ventana
        de la sesión. Se calcula a partir de los account.payment y NO del
        statement.balance_end, porque en Odoo 19 los pagos no generan
        statement lines automáticamente y balance_end queda en 0.
        """
        Payment = self.env['account.payment']
        for l in self:
            stmt = l.session_id.statement_ids.filtered(
                lambda s: s.journal_id == l.journal_id
            )
            balance_start = stmt[0].balance_start if stmt else 0.0
            if l.kind == 'open':
                l.theoretical_amount = balance_start
                continue
            # cierre — sumar payments del journal durante la sesión
            session = l.session_id
            if not session.date_open:
                l.theoretical_amount = balance_start
                continue
            domain = [
                ('journal_id', '=', l.journal_id.id),
                ('state', '=', 'posted'),
                ('date', '>=', fields.Date.to_date(session.date_open)),
            ]
            if session.date_close:
                domain.append(('date', '<=', fields.Date.to_date(session.date_close)))
            payments = Payment.search(domain)
            inbound = sum(p.amount for p in payments if p.payment_type == 'inbound')
            outbound = sum(p.amount for p in payments if p.payment_type == 'outbound')
            l.theoretical_amount = balance_start + inbound - outbound

    @api.depends('physical_amount', 'theoretical_amount', 'kind')
    def _compute_difference(self):
        for l in self:
            # Solo aplica al cierre (la apertura es el dato base, no hay diferencia)
            if l.kind == 'close':
                l.difference = (l.physical_amount or 0.0) - (l.theoretical_amount or 0.0)
            else:
                l.difference = 0.0
