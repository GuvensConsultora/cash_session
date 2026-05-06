from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cash_difference_account_id = fields.Many2one(
        related='company_id.cash_difference_account_id',
        readonly=False,
    )
    cash_central_journal_id = fields.Many2one(
        related='company_id.cash_central_journal_id',
        readonly=False,
    )
