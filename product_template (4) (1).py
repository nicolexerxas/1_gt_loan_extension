# -*- coding: utf-8 -*-
from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    is_loan_product = fields.Boolean(
        string='É Produto de Empréstimo',
        default=False,
        help='Marque se este produto representa um empréstimo'
    )
    
    loan_interest_rate = fields.Float(
        string='Taxa de Juros Padrão (%)',
        default=10.0,
        help='Taxa de juros padrão por período'
    )
    
    loan_interest_period = fields.Integer(
        string='Período de Juros (dias)',
        default=7,
        help='Período em dias para aplicação da taxa de juros'
    )
    
    @api.onchange('is_loan_product')
    def _onchange_is_loan_product(self):
        if self.is_loan_product:
            self.type = 'service'
            self.invoice_policy = 'order'