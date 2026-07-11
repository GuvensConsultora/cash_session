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
        string='Diferencia', compute='_compute_difference',
        currency_field='currency_id',
        help='Físico − Teórico. Positivo = sobrante, negativo = faltante.',
    )
    note = fields.Char(string='Observación')
    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True,
    )

    @api.depends('journal_id', 'session_id', 'session_id.date_open',
                 'session_id.date_close', 'session_id.state', 'kind',
                 'session_id.membership_by_link')
    def _compute_theoretical(self):
        AML = self.env['account.move.line']
        Payment = self.env['account.payment']
        for l in self:
            if l.kind == 'open':
                l.theoretical_amount = 0.0
                continue
            session = l.session_id
            journal = l.journal_id
            if not journal or not session.date_open:
                l.theoretical_amount = 0.0
                continue
            accs = journal.default_account_id
            for pml in (journal.inbound_payment_method_line_ids
                        | journal.outbound_payment_method_line_ids):
                if pml.payment_account_id:
                    accs |= pml.payment_account_id
            if not accs:
                l.theoretical_amount = 0.0
                continue
            if session.membership_by_link:
                # Pertenencia por vínculo: el teórico suma los movimientos sobre
                # las cuentas de la caja de los payments estampados a esta sesión
                # (turnos intra-día exactos). La transferencia de cierre no es un
                # payment, así que no entra: el teórico = cobros/pagos del turno,
                # estable aunque la sesión se recompute después del cierre.
                payments = Payment.sudo().search([
                    ('cash_session_id', '=', session.id),
                    ('journal_id', '=', journal.id),
                    # Solo pagos que efectivamente mueven plata en la caja:
                    # 'canceled'/'rejected' siguen con su asiento posteado (la
                    # anulación es por reversión, no por borrado del move) y NO
                    # corresponden al efectivo del turno. Filtrarlos por estado
                    # del payment, no por el move. 'draft' tampoco cuenta.
                    ('state', 'in', ['in_process', 'paid']),
                ])
                moves = payments.move_id
                if not moves:
                    l.theoretical_amount = 0.0
                    continue
                domain = [
                    ('move_id', 'in', moves.ids),
                    ('account_id', 'in', accs.ids),
                    ('parent_state', '=', 'posted'),
                ]
                l.theoretical_amount = sum(AML.sudo().search(domain).mapped('balance'))
                continue
            # Legacy (sesiones históricas): por fecha contable (date), no
            # create_date. Recibos migrados/backdated (date retroactiva, creados
            # dentro de la sesión actual) NO corresponden a la caja física de hoy.
            date_from = fields.Date.to_date(session.date_open)
            domain = [
                ('journal_id', '=', journal.id),
                ('account_id', 'in', accs.ids),
                ('parent_state', '=', 'posted'),
                ('date', '>=', date_from),
            ]
            if session.state == 'closed' and session.date_close:
                domain.append(('date', '<=', fields.Date.to_date(session.date_close)))
            l.theoretical_amount = sum(AML.search(domain).mapped('balance'))

    @api.depends('physical_amount', 'theoretical_amount', 'kind')
    def _compute_difference(self):
        for l in self:
            # Solo aplica al cierre (la apertura es el dato base, no hay diferencia)
            if l.kind == 'close':
                l.difference = (l.physical_amount or 0.0) - (l.theoretical_amount or 0.0)
            else:
                l.difference = 0.0
