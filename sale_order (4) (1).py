from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    # Campos do Empréstimo (MANTENDO SUA ESTRUTURA)
    is_loan_order = fields.Boolean(
        string='É Empréstimo',
        compute='_compute_is_loan_order',
        store=True
    )
    
    loan_requested_amount = fields.Monetary(
        string='Valor Solicitado',
        currency_field='currency_id'
    )
    
    loan_released_amount = fields.Monetary(
        string='Valor Liberado',
        currency_field='currency_id',
        help='Valor efetivamente liberado ao cliente'
    )
    
    loan_interest_rate = fields.Float(
        string='Taxa de Juros (%)',
        default=10.0
    )
    
    loan_interest_period = fields.Integer(
        string='Período de Juros (dias)',
        default=7
    )
    
    loan_weeks = fields.Integer(
        string='Número de Semanas',
        default=4
    )
    
    loan_total_amount = fields.Monetary(
        string='Total a Pagar',
        compute='_compute_loan_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    loan_installment_amount = fields.Monetary(
        string='Valor da Parcela',
        compute='_compute_loan_amounts',
        store=True,
        currency_field='currency_id'
    )
    
    loan_status = fields.Selection([
        ('draft', 'Rascunho'),
        ('active', 'Ativo'),
        ('late', 'Atrasado'),
        ('paid', 'Quitado'),
        ('defaulted', 'Inadimplente'),
        ('renegotiated', 'Renegociado')
    ], string='Status do Empréstimo', default='draft', tracking=True)
    
    loan_start_date = fields.Date(
        string='Data de Início',
        default=fields.Date.today
    )
    
    loan_installment_ids = fields.One2many(
        'loan.installment',
        'sale_order_id',
        string='Parcelas'
    )
    
    loan_balance = fields.Monetary(
        string='Saldo Devedor',
        compute='_compute_loan_balance',
        store=True,
        currency_field='currency_id'
    )
    
    is_loan_renegotiation = fields.Boolean(
        string='É Renegociação',
        default=False
    )
    
    loan_origin_order_id = fields.Many2one(
        'sale.order',
        string='Empréstimo Original',
        domain=[('is_loan_order', '=', True)]
    )
    
    # NOVOS CAMPOS PARA CONTROLE DE PARCELAS
    installments_count = fields.Integer(
        string='Número de Parcelas', 
        compute='_compute_installments_count'
    )
    
    installments_generated = fields.Boolean(
        string='Parcelas Geradas', 
        compute='_compute_installments_generated',
        store=True
    )
    
    # ===============================================
    # NOVO CAMPO PARA RENEGOCIAÇÃO DE PARCELAS
    # ===============================================
    overdue_installments_count = fields.Integer(
        string='Parcelas Atrasadas',
        compute='_compute_installment_stats'
    )
    
    @api.depends('order_line.product_id.is_loan_product')
    def _compute_is_loan_order(self):
        for order in self:
            order.is_loan_order = any(line.product_id.is_loan_product for line in order.order_line)
    
    @api.depends('loan_released_amount', 'loan_interest_rate', 'loan_weeks', 'loan_interest_period')
    def _compute_loan_amounts(self):
        for order in self:
            if order.is_loan_order and order.loan_released_amount and order.loan_weeks:
                # Calcula juros compostos
                total_days = order.loan_weeks * 7
                interest_periods = total_days / (order.loan_interest_period or 7)
                
                order.loan_total_amount = order.loan_released_amount * (
                    (1 + order.loan_interest_rate / 100) ** interest_periods
                )
                
                order.loan_installment_amount = order.loan_total_amount / order.loan_weeks if order.loan_weeks else 0
                
                # Atualiza o valor da linha do pedido
                loan_lines = order.order_line.filtered(lambda l: l.product_id.is_loan_product)
                for line in loan_lines:
                    line.price_unit = order.loan_total_amount
                    
            else:
                order.loan_total_amount = 0
                order.loan_installment_amount = 0
    
    @api.depends('loan_installment_ids')
    def _compute_installments_count(self):
        for order in self:
            order.installments_count = len(order.loan_installment_ids)
    
    @api.depends('loan_installment_ids')
    def _compute_installments_generated(self):
        for order in self:
            order.installments_generated = bool(order.loan_installment_ids)
    
    @api.depends('loan_installment_ids.amount_paid')
    def _compute_loan_balance(self):
        for order in self:
            total_due = sum(order.loan_installment_ids.mapped('amount'))
            total_paid = sum(order.loan_installment_ids.mapped('amount_paid'))
            order.loan_balance = total_due - total_paid
    
    # ===============================================
    # NOVO MÉTODO COMPUTE PARA RENEGOCIAÇÃO
    # ===============================================
    @api.depends('loan_installment_ids.status')
    def _compute_installment_stats(self):
        """Calcula estatísticas das parcelas"""
        for order in self:
            if order.is_loan_order:
                overdue_count = len(order.loan_installment_ids.filtered(
                    lambda i: i.status in ['late', 'partial']
                ))
                order.overdue_installments_count = overdue_count
            else:
                order.overdue_installments_count = 0
    
    def _get_next_business_day(self, date):
        """Retorna o próximo dia útil (pula fins de semana)"""
        while date.weekday() in [5, 6]:  # Sábado = 5, Domingo = 6
            date += timedelta(days=1)
        return date
    
    def action_generate_loan_installments(self):
        """Gera as parcelas do empréstimo - VERSÃO MELHORADA"""
        self.ensure_one()
        
        if not self.is_loan_order:
            raise UserError('Esta não é uma ordem de empréstimo!')
        
        if not self.loan_released_amount or not self.loan_weeks:
            raise UserError('Defina o valor liberado e número de semanas!')
        
        _logger.info(f"Gerando parcelas para empréstimo {self.name}")
        
        # Remove parcelas existentes
        if self.loan_installment_ids:
            _logger.info(f"Removendo {len(self.loan_installment_ids)} parcelas existentes")
            self.loan_installment_ids.unlink()
        
        # Calcula primeira data de vencimento (próxima semana)
        due_date = self.loan_start_date + timedelta(days=7)
        due_date = self._get_next_business_day(due_date)
        
        # Cria as parcelas
        installment_obj = self.env['loan.installment']
        installments_created = []
        
        for i in range(self.loan_weeks):
            installment_data = {
                'sale_order_id': self.id,
                'number': i + 1,
                'due_date': due_date,
                'amount': self.loan_installment_amount,
                'partner_id': self.partner_id.id,
            }
            
            installment = installment_obj.create(installment_data)
            installments_created.append(installment.id)
            
            _logger.info(f"Criando parcela {i + 1}: R$ {self.loan_installment_amount:.2f} - Vencimento: {due_date}")
            
            # Próxima data (adiciona 7 dias)
            due_date = due_date + timedelta(days=7)
            due_date = self._get_next_business_day(due_date)
        
        # Atualiza status
        self.loan_status = 'active'
        
        # Adiciona mensagem no chatter
        self.message_post(
            body=f"✅ Parcelas geradas com sucesso: {self.loan_weeks} parcelas de "
                 f"{self.currency_id.symbol} {self.loan_installment_amount:,.2f} cada. "
                 f"Total: {self.currency_id.symbol} {self.loan_total_amount:,.2f}"
        )
        
        _logger.info(f"Parcelas criadas com sucesso: {installments_created}")
        
        return True
    
    def action_view_installments(self):
        """Abre janela com todas as parcelas do empréstimo - VERSÃO ODOO 18"""
        self.ensure_one()
        
        if not self.is_loan_order:
            raise UserError("Esta não é uma ordem de empréstimo!")
        
        if self.installments_count == 0:
            raise UserError("Nenhuma parcela encontrada! Gere as parcelas primeiro.")
        
        return {
            'name': f'Parcelas - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'loan.installment',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {
                'default_sale_order_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
            'target': 'current',
        }
    
    def action_open_renegotiation_wizard(self):
        """Abre o wizard de renegociação"""
        self.ensure_one()
        
        if not self.is_loan_order:
            raise UserError("Esta ação só pode ser executada em empréstimos")
        
        if self.loan_status not in ['active', 'late']:
            raise UserError("Só é possível renegociar empréstimos ativos ou atrasados")
        
        return {
            'name': 'Renegociar Empréstimo',
            'type': 'ir.actions.act_window',
            'res_model': 'loan.renegotiation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_original_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_balance_due': self.loan_balance,
            }
        }
    
    # ===============================================
    # NOVO MÉTODO PARA RENEGOCIAÇÃO DE PARCELAS
    # ===============================================
    def action_open_installment_renegotiation_wizard(self):
        """Abre wizard de renegociação de parcelas atrasadas"""
        self.ensure_one()
        
        if not self.is_loan_order:
            raise UserError("Esta ação só pode ser executada em empréstimos")
        
        if self.overdue_installments_count == 0:
            raise UserError("Não há parcelas atrasadas para renegociar")
        
        return {
            'name': 'Renegociar Parcelas Atrasadas',
            'type': 'ir.actions.act_window',
            'res_model': 'loan.installment.renegotiation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
            }
        }
    
    def action_confirm(self):
        """Override para configurar linha de empréstimo ao confirmar"""
        # Primeiro confirma o pedido
        res = super(SaleOrder, self).action_confirm()
        
        # Para pedidos de empréstimo, gera parcelas automaticamente se configurado
        for order in self.filtered('is_loan_order'):
            if order.loan_released_amount and order.loan_weeks and not order.loan_installment_ids:
                # Só gera automaticamente se não houver parcelas
                order.action_generate_loan_installments()
        
        return res
    
    # MÉTODOS PARA AUTOMAÇÃO E CONTROLE
    @api.model
    def _cron_update_loan_status(self):
        """Atualiza status dos empréstimos automaticamente"""
        today = fields.Date.today()
        
        # Busca empréstimos ativos com parcelas vencidas
        active_loans = self.search([
            ('is_loan_order', '=', True),
            ('loan_status', '=', 'active')
        ])
        
        for loan in active_loans:
            overdue_installments = loan.loan_installment_ids.filtered(
                lambda i: i.due_date < today and i.status in ['pending', 'partial']
            )
            
            if overdue_installments:
                loan.loan_status = 'late'
                _logger.info(f"Empréstimo {loan.name} marcado como atrasado")
            
            # Verifica se está quitado
            if all(i.status == 'paid' for i in loan.loan_installment_ids):
                loan.loan_status = 'paid'
                _logger.info(f"Empréstimo {loan.name} quitado")

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    @api.onchange('product_id')
    def _onchange_product_id_loan(self):
        """Configura valores padrão para produtos de empréstimo"""
        if self.product_id and self.product_id.is_loan_product:
            # Define valores padrão do produto de empréstimo
            self.order_id.loan_interest_rate = self.product_id.loan_interest_rate
            self.order_id.loan_interest_period = self.product_id.loan_interest_period
            
            # Configura linha do produto
            self.name = f"Empréstimo - Taxa {self.product_id.loan_interest_rate}% a cada {self.product_id.loan_interest_period} dias"
            self.product_uom_qty = 1
            self.price_unit = 0  # Será calculado depois