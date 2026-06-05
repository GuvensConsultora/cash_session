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
        string='Diferencia total', compute='_compute_difference',
        currency_field='currency_id',
    )
    closing_observations = fields.Text(string='Observaciones del cierre')

    transfer_move_id = fields.Many2one(
        'account.move', string='Asiento de transferencia a caja central',
        readonly=True, copy=False,
    )

    membership_by_link = fields.Boolean(
        string='Pertenencia por vínculo', default=False, readonly=True, copy=False,
        help='Si está activo, los cobros/pagos de esta sesión se determinan por '
             'el vínculo explícito `account.payment.cash_session_id` (estampado '
             'al crear el payment), no por la fecha contable. Permite varios '
             'turnos en el mismo día sin contaminar el arqueo. Las sesiones '
             'nuevas se crean con este modo; las históricas siguen por fecha.',
    )

    currency_id = fields.Many2one(
        related='company_id.currency_id', readonly=True,
    )

    # Detalle de movimientos del turno (control pre-cierre + reporte de cierre).
    # Se computan dinámicamente — sin agregar FKs a account.payment ni
    # account.move.line — filtrando por journal de la caja + rango de fechas.
    # Cheques: en Odoo 19 son un modelo aparte (l10n_latam.check) accesible
    # vía account.payment.l10n_latam_new_check_ids.
    check_ids = fields.Many2many(
        'l10n_latam.check', string='Cheques recibidos',
        compute='_compute_session_payments',
    )
    card_payment_ids = fields.Many2many(
        'account.payment', string='Cupones tarjeta',
        compute='_compute_session_payments',
    )
    check_count = fields.Integer(compute='_compute_session_payments')
    card_count = fields.Integer(compute='_compute_session_payments')
    check_total = fields.Monetary(
        compute='_compute_session_payments', currency_field='currency_id',
    )
    card_total = fields.Monetary(
        compute='_compute_session_payments', currency_field='currency_id',
    )
    withholding_line_ids = fields.Many2many(
        'account.move.line', string='Retenciones sufridas',
        compute='_compute_withholding_lines',
    )
    withholding_count = fields.Integer(compute='_compute_withholding_lines')
    withholding_total = fields.Monetary(
        compute='_compute_withholding_lines', currency_field='currency_id',
    )

    @api.depends('closing_line_ids.difference')
    def _compute_difference(self):
        for s in self:
            s.difference_total = sum(s.closing_line_ids.mapped('difference'))

    def _session_payment_domain(self):
        """Domain base para localizar los cobros (inbound) del turno.

        Dos modos:
        - `membership_by_link` (sesiones nuevas): pertenencia por el vínculo
          explícito `cash_session_id`, estampado al crear el payment. Permite
          varios turnos el mismo día sin contaminar el arqueo.
        - Legacy (sesiones históricas): pertenencia por fecha contable (día),
          entre apertura y cierre (o ahora si no cerró). Se conserva tal cual
          para no alterar el arqueo de las sesiones ya cerradas. Filtra por
          `date`, no `create_date`: los cobros migrados con fecha retroactiva
          NO deben sumarse a la caja física del turno.
        """
        self.ensure_one()
        if not self.cash_register_id:
            return None
        base = [
            ('journal_id', 'in', self.cash_register_id.journal_ids.ids),
            ('state', '!=', 'draft'),
            ('company_id', '=', self.company_id.id),
            ('payment_type', '=', 'inbound'),
        ]
        if self.membership_by_link:
            return base + [('cash_session_id', '=', self.id)]
        if not self.date_open:
            return None
        date_from = fields.Date.to_date(self.date_open)
        date_to = fields.Date.to_date(self.date_close or fields.Datetime.now())
        return base + [('date', '>=', date_from), ('date', '<=', date_to)]

    @api.depends('cash_register_id', 'cash_register_id.journal_ids',
                 'date_open', 'date_close', 'state')
    def _compute_session_payments(self):
        Payment = self.env['account.payment']
        Check = self.env['l10n_latam.check']
        for s in self:
            domain = s._session_payment_domain()
            if domain is None:
                s.check_ids = Check
                s.card_payment_ids = Payment
                s.check_count = s.card_count = 0
                s.check_total = s.card_total = 0.0
                continue
            check_journals = s.cash_register_id.journal_ids.filtered(
                lambda j: j.cash_session_kind == 'third_party_check'
            )
            card_journals = s.cash_register_id.journal_ids.filtered(
                lambda j: j.cash_session_kind == 'card'
            )
            check_payments = Payment.search(domain + [
                ('journal_id', 'in', check_journals.ids),
            ]) if check_journals else Payment
            cards = Payment.search(domain + [
                ('journal_id', 'in', card_journals.ids),
            ]) if card_journals else Payment
            checks = check_payments.mapped('l10n_latam_new_check_ids')
            s.check_ids = checks
            s.card_payment_ids = cards
            s.check_count = len(checks)
            s.card_count = len(cards)
            s.check_total = sum(checks.mapped('amount'))
            s.card_total = sum(cards.mapped('amount'))

    @api.depends('cash_register_id', 'cash_register_id.journal_ids',
                 'date_open', 'date_close', 'state')
    def _compute_withholding_lines(self):
        MoveLine = self.env['account.move.line']
        for s in self:
            domain = s._session_payment_domain()
            if domain is None:
                s.withholding_line_ids = MoveLine
                s.withholding_count = 0
                s.withholding_total = 0.0
                continue
            payments = self.env['account.payment'].search(domain)
            moves = payments.mapped('move_id')
            if not moves:
                s.withholding_line_ids = MoveLine
                s.withholding_count = 0
                s.withholding_total = 0.0
                continue
            lines = MoveLine.search([
                ('move_id', 'in', moves.ids),
                ('tax_line_id', '!=', False),
            ])
            # Filtrar a retenciones AR (l10n_ar_withholding). El campo solo
            # existe si la localización AR está instalada; defensivo con getattr.
            lines = lines.filtered(
                lambda l: getattr(l.tax_line_id, 'l10n_ar_withholding_payment_type', False)
            )
            s.withholding_line_ids = lines
            s.withholding_count = len(lines)
            # Importe retenido = balance absoluto (las retenciones suelen
            # registrarse en debit o credit según corresponda).
            s.withholding_total = sum(abs(l.balance) for l in lines)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        Sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            # Sesiones nuevas: pertenencia por vínculo. Las históricas quedaron
            # en False (default del campo) al actualizar el módulo.
            vals.setdefault('membership_by_link', True)
            if vals.get('name', _('Nueva')) != _('Nueva'):
                continue
            register = self.env['cash.register'].browse(vals.get('cash_register_id'))
            if not register:
                continue
            code_short = (register.code or 'CAJA').upper().replace('/', '-')
            seq_code = 'cash.session.%s' % (register.code or register.id)
            seq = Sequence.search([('code', '=', seq_code)], limit=1)
            if not seq:
                seq = Sequence.create({
                    'name': 'Sesiones %s' % register.display_name,
                    'code': seq_code,
                    'prefix': '%s/%%(range_year)s/' % code_short,
                    'padding': 5,
                    'use_date_range': True,
                    'company_id': register.company_id.id,
                })
            # next_by_id bypassea el filtro de company que sí aplica
            # next_by_code, evitando que devuelva None cuando el user
            # actual no tiene la company del register entre sus
            # allowed_company_ids al momento del create.
            vals['name'] = seq.next_by_id() or _('Nueva')
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
        - Genera el asiento de transferencia a caja central SOLO por el efectivo
          (cheques de terceros y tarjetas se informan en el cierre, no se transfieren).
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

        # 2. Transferir a caja central SOLO el efectivo
        self._transfer_to_central()

        self.state = 'closed'

    def _transfer_to_central(self):
        """Genera el/los asiento/s de transferencia al cierre.

        Caso intra-company (caja central en la misma compañía de la sesión):
        un único asiento con las líneas de cada journal de la caja contra la
        cuenta de la caja central.

        Caso inter-company (RT 9 FACPCE: caja central en OTRA compañía):
        dos asientos espejo, uno en cada compañía, usando las cuentas
        intercompany configuradas. El crédito a cobrar y la deuda a pagar
        van separados (no se compensan en una sola cuenta bidireccional).
        """
        self.ensure_one()
        company_origen = self.company_id
        central = company_origen.cash_central_journal_id
        if not central:
            return

        # Solo se transfiere EFECTIVO a la caja central. Cheques de terceros y
        # tarjetas se recuentan e informan en el cierre, pero quedan en su
        # journal (no se transfieren).
        breakdown = []  # list of (journal, amount)
        for cl in self.closing_line_ids:
            j = cl.journal_id
            if j.cash_session_kind != 'cash':
                continue
            amount = cl.physical_amount
            if not amount or not j.default_account_id:
                continue
            breakdown.append((j, amount))

        if not breakdown:
            return

        company_destino = central.company_id
        if company_destino == company_origen:
            self._transfer_to_central_intra(central, breakdown)
        else:
            self._transfer_to_central_inter(central, company_destino, breakdown)

    def _transfer_to_central_intra(self, central, breakdown):
        """Asiento único intra-company: cada journal CR su cuenta y DR la
        cuenta de la caja central. Una sola compañía interviene."""
        self.ensure_one()
        company = self.company_id
        Move = self.env['account.move']
        dest_acc = central.default_account_id
        if not dest_acc:
            raise UserError(_(
                'El journal de caja central "%s" no tiene cuenta por defecto.',
                central.display_name,
            ))
        move_lines = []
        for j, amount in breakdown:
            label = _('Cierre %(s)s — %(j)s') % {'s': self.name, 'j': j.code or j.name}
            move_lines.append((0, 0, {
                'account_id': j.default_account_id.id, 'name': label,
                'credit': amount, 'debit': 0,
            }))
            move_lines.append((0, 0, {
                'account_id': dest_acc.id, 'name': label,
                'debit': amount, 'credit': 0,
            }))
        move = Move.with_company(company).create({
            'journal_id': central.id,
            'date': fields.Date.context_today(self),
            'ref': _('Cierre sesión %s') % self.name,
            'company_id': company.id,
            'line_ids': move_lines,
        })
        move.with_company(company).action_post()
        self.transfer_move_id = move.id

    def _transfer_to_central_inter(self, central, company_destino, breakdown):
        """Dos asientos espejo en distintas compañías.

        Compañía origen (la de la sesión): por cada journal CR su cuenta;
        DR la cta. cte. intercompany "a cobrar" por el total. Refleja que
        la otra compañía nos queda debiendo.

        Compañía destino (la del journal central): DR la cuenta de la caja
        central por el total; CR la cta. cte. intercompany "a pagar". Refleja
        que le quedamos debiendo a la otra compañía.

        RT 9 FACPCE: saldos con sociedades vinculadas separados activo/pasivo.
        """
        self.ensure_one()
        company_origen = self.company_id

        ic_recv = company_origen.cash_intercompany_receivable_id
        ic_pay = company_destino.cash_intercompany_payable_id
        if not ic_recv:
            raise UserError(_(
                'Falta configurar la cuenta intercompany "a cobrar" en %s '
                'para registrar la transferencia a la caja central de %s.',
                company_origen.display_name, company_destino.display_name,
            ))
        if not ic_pay:
            raise UserError(_(
                'Falta configurar la cuenta intercompany "a pagar" en %s '
                'para recibir la transferencia desde %s.',
                company_destino.display_name, company_origen.display_name,
            ))
        dest_acc = central.default_account_id
        if not dest_acc:
            raise UserError(_(
                'El journal de caja central "%s" no tiene cuenta por defecto.',
                central.display_name,
            ))

        Journal = self.env['account.journal']
        origin_journal = Journal.search([
            ('company_id', '=', company_origen.id), ('type', '=', 'general'),
        ], limit=1)
        if not origin_journal:
            origin_journal = Journal.search([
                ('company_id', '=', company_origen.id), ('type', '=', 'cash'),
            ], limit=1)
        if not origin_journal:
            raise UserError(_(
                'No hay un journal apto en %s para registrar el asiento '
                'intercompany de transferencia.',
                company_origen.display_name,
            ))

        total = sum(a for _j, a in breakdown)
        ref_label = _(
            'Transferencia cierre %(s)s — caja central %(c)s'
        ) % {'s': self.name, 'c': company_destino.display_name}

        Move = self.env['account.move']

        # Asiento en compañía origen
        move_lines_origen = []
        for j, amount in breakdown:
            line_label = _('Cierre %(s)s — %(j)s') % {
                's': self.name, 'j': j.code or j.name,
            }
            move_lines_origen.append((0, 0, {
                'account_id': j.default_account_id.id, 'name': line_label,
                'credit': amount, 'debit': 0,
            }))
        move_lines_origen.append((0, 0, {
            'account_id': ic_recv.id, 'name': ref_label,
            'debit': total, 'credit': 0,
        }))
        move_origen = Move.with_company(company_origen).create({
            'journal_id': origin_journal.id,
            'date': fields.Date.context_today(self),
            'ref': ref_label,
            'company_id': company_origen.id,
            'line_ids': move_lines_origen,
        })
        move_origen.with_company(company_origen).action_post()

        # Asiento espejo en compañía destino
        move_lines_destino = [
            (0, 0, {
                'account_id': dest_acc.id, 'name': ref_label,
                'debit': total, 'credit': 0,
            }),
            (0, 0, {
                'account_id': ic_pay.id, 'name': ref_label,
                'credit': total, 'debit': 0,
            }),
        ]
        move_destino = Move.with_company(company_destino).create({
            'journal_id': central.id,
            'date': fields.Date.context_today(self),
            'ref': ref_label,
            'company_id': company_destino.id,
            'line_ids': move_lines_destino,
        })
        move_destino.with_company(company_destino).action_post()

        self.transfer_move_id = move_origen.id

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
