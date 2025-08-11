# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class LoanRenegotiationWizard(models.TransientModel):
    _name = 'loan.renegotiation.wizard'
    _description = 'Wizard de Renegociação de Empréstimo'
    
    original_order_id = fields.Many2one(
        'sale.order',
        string='Empréstimo Original',
        required=True,
        readonly=True
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        readonly=True
    )
    
    balance_due = fields.Monetary(
        string='Saldo Devedor',
        currency_field='currency_id',
        readonly=True
    )
    
    new_loan_amount = fields.Monetary(
        string='Valor do Novo Empréstimo',
        currency_field='currency_id',
        required=True
    )
    
    amount_to_client = fields.Monetary(
        string='Valor para o Cliente',
        currency_field='currency_id',
        compute='_compute_amount_to_client'
    )
    
    interest_rate = fields.Float(
        string='Taxa de Juros (%)',
        required=True,
        default=10.0
    )
    
    weeks = fields.Integer(
        string='Número de Semanas',
        required=True,
        default=4
    )
    
    start_date = fields.Date(
        string='Data de Início',
        default=fields.Date.today,
        required=True
    )
    
    notes = fields.Text(
        string='Observações'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='original_order_id.currency_id'
    )
    
    @api.depends('new_loan_amount', 'balance_due')
    def _compute_amount_to_client(self):
        for rec in self:
            rec.amount_to_client = rec.new_loan_amount - rec.balance_due
    
    @api.constrains('new_loan_amount', 'balance_due')
    def _check_new_loan_amount(self):
        for rec in self:
            if rec.new_loan_amount <= rec.balance_due:
                raise ValidationError(
                    f'O valor do novo empréstimo deve ser maior que o saldo devedor '
                    f'({rec.currency_id.symbol} {rec.balance_due:,.2f})'
                )
    
    def action_confirm_renegotiation(self):
        """Confirma a renegociação"""
        self.ensure_one()
        
        # Busca produto de empréstimo
        loan_product = self.env['product.product'].search([
            ('is_loan_product', '=', True)
        ], limit=1)
        
        if not loan_product:
            raise ValidationError('Nenhum produto de empréstimo encontrado!')
        
        # Cria nova ordem de venda (novo empréstimo)
        new_order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'is_loan_renegotiation': True,
            'loan_origin_order_id': self.original_order_id.id,
            'loan_requested_amount': self.new_loan_amount,
            'loan_released_amount': self.amount_to_client,
            'loan_interest_rate': self.interest_rate,
            'loan_weeks': self.weeks,
            'loan_start_date': self.start_date,
            'order_line': [(0, 0, {
                'product_id': loan_product.id,
                'name': f'Renegociação - Empréstimo {self.weeks} semanas',
                'product_uom_qty': 1,
            })],
        })
        
        # Marca parcelas antigas como pagas
        unpaid_installments = self.original_order_id.loan_installment_ids.filtered(
            lambda i: i.status != 'paid'
        )
        
        for installment in unpaid_installments:
            installment.write({
                'amount_paid': installment.amount,
                'payment_date': fields.Date.today(),
            })
        
        # Atualiza status do empréstimo original
        self.original_order_id.write({
            'loan_status': 'renegotiated',
        })
        
        # Retorna ação para abrir o novo empréstimo
        return {
            'name': 'Novo Empréstimo',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': new_order.id,
            'view_mode': 'form',
            'target': 'current',
        }
