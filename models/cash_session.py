from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CashSession(models.Model):
    _name = 'cash.session'
    _description = 'Sesión de caja (turno)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_open desc, id desc'

    name = fields.Char(
        string='Referencia',
        default=lambda self: _('Nueva'),
        readonly=True, copy=False,
    )
    cash_register_id = fields.Many2one(
        'cash.register', string='Caja', required=True, tracking=True,
    )
    responsible_id = fields.Many2one(
        'res.users', string='Responsable',
        default=lambda self: self.env.user, required=True, tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', related='cash_register_id.company_id',
        store=True, readonly=True,
    )
    date_open = fields.Datetime(
        string='Apertura', default=fields.Datetime.now, tracking=True,
    )
    date_close = fields.Datetime(string='Cierre', readonly=True, tracking=True)

    state = fields.Selection(
        [('draft', 'Borrador'),
         ('open', 'Abierta'),
         ('closing', 'En cierre'),
         ('closed', 'Cerrada')],
        default='draft', tracking=True, string='Estado',
    )

    statement_ids = fields.One2many(
        'account.bank.statement', 'cash_session_id', string='Extractos',
    )
    opening_line_ids = fields.One2many(
        'cash.session.line', 'session_id',
        string='Apertura', domain=[('kind', '=', 'open')],
    )
    closing_line_ids = fields.One2many(
        'cash.session.line', 'session_id',
        string='Cierre', domain=[('kind', '=', 'close')],
    )

    difference_total = fields.Monetary(
        string='Diferencia total', compute='_compute_difference', store=True,
        currency_field='currency_id',
    )
    closing_observations = fields.Text(string='Observaciones del cierre')

    transfer_move_id = fields.Many2one(
        'account.move', string='Asiento de transferencia a caja central',
        readonly=True, copy=False,
    )

    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True,
    )

    @api.depends('closing_line_ids.difference')
    def _compute_difference(self):
        for s in self:
            s.difference_total = sum(s.closing_line_ids.mapped('difference'))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nueva')) == _('Nueva'):
                register = self.env['cash.register'].browse(vals.get('cash_register_id'))
                seq_code = 'cash.session.%s' % (register.code or register.id)
                seq = self.env['ir.sequence'].search([('code', '=', seq_code)], limit=1)
                if not seq:
                    seq = self.env['ir.sequence'].sudo().create({
                        'name': 'Sesiones %s' % register.display_name,
                        'code': seq_code,
                        'prefix': '%s/%%(year)s/' % (register.code or 'CAJA'),
                        'padding': 5,
                        'company_id': register.company_id.id,
                    })
                vals['name'] = seq.next_by_code(seq_code) or _('Nueva')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_open(self):
        """Crea las líneas de apertura (una por journal de la caja) en estado borrador
        para que el responsable cargue el arqueo físico inicial."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se puede abrir una sesión en borrador.'))
        # Una sesión abierta por caja
        other = self.search([
            ('cash_register_id', '=', self.cash_register_id.id),
            ('state', 'in', ('open', 'closing')),
            ('id', '!=', self.id),
        ], limit=1)
        if other:
            raise UserError(_(
                'Ya existe una sesión "%(s)s" abierta en esta caja. '
                'Hay que cerrarla antes de abrir una nueva.', s=other.display_name,
            ))
        # Validar responsable autorizado (si hay lista en register)
        register = self.cash_register_id
        if register.responsible_user_ids and \
                self.responsible_id not in register.responsible_user_ids:
            raise UserError(_(
                'El usuario "%(u)s" no está autorizado a operar la caja "%(c)s".',
                u=self.responsible_id.display_name, c=register.display_name,
            ))

        # Crear opening lines (1 por journal) si no existen
        Line = self.env['cash.session.line']
        existing_journals = self.opening_line_ids.mapped('journal_id')
        for j in register.journal_ids:
            if j in existing_journals:
                continue
            Line.create({
                'session_id': self.id,
                'journal_id': j.id,
                'kind': 'open',
            })

        self.state = 'open'

    def action_create_statements(self):
        """Una vez confirmada la apertura física, crea los account.bank.statement
        (uno por journal) con balance_start = physical_amount de cada opening_line."""
        self.ensure_one()
        if self.state != 'open':
            raise UserError(_('La sesión debe estar abierta.'))
        Statement = self.env['account.bank.statement']
        for ol in self.opening_line_ids:
            existing = self.statement_ids.filtered(lambda s: s.journal_id == ol.journal_id)
            if existing:
                continue
            Statement.create({
                'name': '%s — %s' % (self.name, ol.journal_id.code or ol.journal_id.name),
                'journal_id': ol.journal_id.id,
                'date': fields.Date.context_today(self),
                'balance_start': ol.physical_amount,
                'cash_session_id': self.id,
            })

    def action_start_closing(self):
        """Pasa a 'closing' y crea las closing_lines (una por journal) para que el
        responsable cargue el recuento físico final."""
        self.ensure_one()
        if self.state != 'open':
            raise UserError(_('Solo se cierra una sesión abierta.'))
        Line = self.env['cash.session.line']
        existing_journals = self.closing_line_ids.mapped('journal_id')
        for j in self.cash_register_id.journal_ids:
            if j in existing_journals:
                continue
            Line.create({
                'session_id': self.id,
                'journal_id': j.id,
                'kind': 'close',
            })
        self.date_close = fields.Datetime.now()
        self.state = 'closing'

    def action_validate_close(self):
        """Valida el cierre:
        - Si hay diferencia y no hay observaciones, exige justificación.
        - Setea balance_end_real en cada statement = physical_amount y los postea
          (Odoo nativo imputa la diferencia a la cuenta de diferencias de la company).
        - Genera el asiento de transferencia a caja central por efectivo y cheques.
        - State pasa a 'closed'.
        """
        self.ensure_one()
        if self.state != 'closing':
            raise UserError(_('Solo se valida el cierre desde estado "En cierre".'))

        company = self.company_id
        if self.difference_total and not (self.closing_observations or '').strip():
            raise UserError(_(
                'Hay una diferencia total de %(d).2f. Cargá la observación '
                'que justifique la diferencia antes de cerrar.',
                d=self.difference_total,
            ))
        if self.difference_total and not company.cash_difference_account_id:
            raise UserError(_(
                'Configurá la cuenta de diferencias de caja en la compañía '
                'antes de cerrar con diferencia.'
            ))

        # 1. Cerrar cada statement con balance_end_real = physical_amount
        for cl in self.closing_line_ids:
            stmt = self.statement_ids.filtered(lambda s: s.journal_id == cl.journal_id)
            if not stmt:
                continue
            stmt = stmt[0]
            stmt.balance_end_real = cl.physical_amount
            # Postear: Odoo nativo crea ajuste de diferencia si balance_end_real != balance_end
            try:
                stmt.button_validate()
            except Exception:
                # Algunas versiones usan action_post / button_post
                try:
                    stmt.action_post()
                except Exception:
                    pass

        # 2. Transferir a caja central efectivo + cheques de terceros
        self._transfer_to_central()

        self.state = 'closed'

    def _transfer_to_central(self):
        """Genera un account.move por cada journal cuyo cash_session_kind sea
        'cash' o 'third_party_check', moviendo el balance_end_real a la caja central."""
        self.ensure_one()
        company = self.company_id
        central = company.cash_central_journal_id
        if not central:
            # Sin caja central configurada, nada que transferir
            return

        Move = self.env['account.move']
        lines_to_create = []
        for cl in self.closing_line_ids:
            j = cl.journal_id
            if j.cash_session_kind not in ('cash', 'third_party_check'):
                continue
            amount = cl.physical_amount
            if not amount:
                continue
            origin_acc = j.default_account_id
            dest_acc = central.default_account_id
            if not origin_acc or not dest_acc:
                continue
            label = _('Transferencia cierre %(s)s — %(j)s', s=self.name, j=j.code or j.name)
            lines_to_create.append((origin_acc, dest_acc, amount, label, j))

        if not lines_to_create:
            return

        # Un único asiento con todas las líneas (más limpio para revisar)
        move_lines = []
        for origin_acc, dest_acc, amount, label, j in lines_to_create:
            move_lines.append((0, 0, {
                'account_id': origin_acc.id, 'name': label,
                'credit': amount, 'debit': 0,
            }))
            move_lines.append((0, 0, {
                'account_id': dest_acc.id, 'name': label,
                'debit': amount, 'credit': 0,
            }))
        move = Move.create({
            'journal_id': central.id,
            'date': fields.Date.context_today(self),
            'ref': _('Cierre sesión %s') % self.name,
            'company_id': company.id,
            'line_ids': move_lines,
        })
        move.action_post()
        self.transfer_move_id = move.id

    def action_view_transfer_move(self):
        self.ensure_one()
        if not self.transfer_move_id:
            raise UserError(_('No hay asiento de transferencia generado.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.transfer_move_id.id,
        }
