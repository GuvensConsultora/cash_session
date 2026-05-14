from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CashRegister(models.Model):
    _name = 'cash.register'
    _description = 'Caja física'
    _order = 'company_id, name'

    name = fields.Char(string='Nombre', required=True)
    code = fields.Char(
        string='Código',
        size=8,
        help='Código corto. Se usa como prefijo de la secuencia de sesiones.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    journal_ids = fields.Many2many(
        'account.journal',
        string='Journals que opera',
        domain="[('type', 'in', ['cash', 'bank']), ('company_id', '=', company_id)]",
        required=True,
        help='Journals (efectivo, cheques de terceros, tarjetas) que se arquean '
             'en esta caja. Cada journal tiene su tipo definido en su propia '
             'configuración (campo "Tipo en caja").',
    )
    allow_payments_out = fields.Boolean(
        string='Permite pagos a proveedores',
        default=False,
        help='Si está marcado, esta caja autoriza emitir órdenes de pago '
             '(account.payment outbound). Si NO está marcado, los intentos de '
             'pagar a proveedores desde sus journals son bloqueados.',
    )
    responsible_user_ids = fields.Many2many(
        'res.users',
        string='Responsables autorizados',
        help='Usuarios que pueden abrir y cerrar sesiones en esta caja. '
             'Si está vacío, cualquier usuario con permisos de caja puede operarla.',
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_company_unique',
         'unique(name, company_id)',
         'Ya existe una caja con ese nombre en la compañía.'),
    ]

    @api.constrains('journal_ids', 'company_id')
    def _check_journals_company(self):
        for r in self:
            for j in r.journal_ids:
                if j.company_id and j.company_id != r.company_id:
                    raise ValidationError(_(
                        'El journal "%(j)s" pertenece a otra compañía.',
                        j=j.display_name,
                    ))
