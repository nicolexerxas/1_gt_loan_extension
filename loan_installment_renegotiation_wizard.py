# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class LoanInstallmentRenegotiationWizard(models.TransientModel):
    _name = 'loan.installment.renegotiation.wizard'
    _description = 'Wizard de Renegociação de Parcelas Atrasadas'
    
    # ===================================
    # CAMPOS BÁSICOS
    # ===================================
    
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Empréstimo',
        required=True,
        readonly=True
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        related='sale_order_id.partner_id',
        readonly=True
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='sale_order_id.currency_id',
        readonly=True
    )
    
    # ===================================
    # SITUAÇÃO ATUAL
    # ===================================
    
    current_balance = fields.Monetary(
        string='Saldo Devedor Atual',
        currency_field='currency_id',
        compute='_compute_current_situation',
        store=True,
        help='Valor total das parcelas pendentes'
    )
    
    overdue_installments_count = fields.Integer(
        string='Parcelas Atrasadas',
        compute='_compute_current_situation',
        store=True
    )
    
    pending_installments_count = fields.Integer(
        string='Parcelas Pendentes',
        compute='_compute_current_situation', 
        store=True
    )
    
    days_overdue = fields.Integer(
        string='Dias de Atraso',
        compute='_compute_current_situation',
        store=True
    )
    
    # ===================================
    # NOVOS TERMOS DA RENEGOCIAÇÃO
    # ===================================
    
    renegotiation_type = fields.Selection([
        ('extend', 'Estender Prazo'),
        ('discount', 'Aplicar Desconto'),
        ('new_terms', 'Novos Termos Completos')
    ], string='Tipo de Renegociação', required=True, default='extend')
    
    # Para extensão de prazo
    extension_weeks = fields.Integer(
        string='Estender por (semanas)',
        default=2,
        help='Quantas semanas adicionar ao prazo atual'
    )
    
    # Para desconto
    discount_type = fields.Selection([
        ('percentage', 'Percentual'),
        ('fixed', 'Valor Fixo')
    ], string='Tipo de Desconto', default='percentage')
    
    discount_percentage = fields.Float(
        string='Desconto (%)',
        default=10.0,
        help='Percentual de desconto sobre o saldo devedor'
    )
    
    discount_amount = fields.Monetary(
        string='Valor do Desconto',
        currency_field='currency_id',
        help='Valor fixo de desconto'
    )
    
    # Para novos termos completos
    new_interest_rate = fields.Float(
        string='Nova Taxa de Juros (%)',
        help='Nova taxa de juros para o período restante'
    )
    
    new_weeks = fields.Integer(
        string='Novo Prazo (semanas)',
        help='Novo prazo total em semanas a partir de hoje'
    )
    
    # ===================================
    # CAMPOS CALCULADOS
    # ===================================
    
    new_balance = fields.Monetary(
        string='Novo Saldo',
        currency_field='currency_id',
        compute='_compute_new_terms',
        help='Saldo após aplicar descontos'
    )
    
    new_installment_amount = fields.Monetary(
        string='Nova Parcela',
        currency_field='currency_id',
        compute='_compute_new_terms',
        help='Valor da nova parcela'
    )
    
    new_total_weeks = fields.Integer(
        string='Total de Semanas',
        compute='_compute_new_terms',
        help='Total de semanas do novo cronograma'
    )
    
    renegotiation_start_date = fields.Date(
        string='Data de Início',
        default=fields.Date.today,
        required=True,
        help='Data de início do novo cronograma'
    )
    
    notes = fields.Text(
        string='Observações',
        help='Motivo e detalhes da renegociação'
    )
    
    # ===================================
    # MÉTODOS COMPUTADOS
    # ===================================
    
    @api.depends('sale_order_id.loan_installment_ids')
    def _compute_current_situation(self):
        """Calcula situação atual do empréstimo"""
        for wizard in self:
            if not wizard.sale_order_id:
                wizard.current_balance = 0
                wizard.overdue_installments_count = 0
                wizard.pending_installments_count = 0
                wizard.days_overdue = 0
                continue
            
            installments = wizard.sale_order_id.loan_installment_ids
            
            # Parcelas pendentes (não pagas)
            pending_installments = installments.filtered(
                lambda i: i.status in ['pending', 'late', 'partial']
            )
            
            # Parcelas atrasadas
            overdue_installments = installments.filtered(
                lambda i: i.status in ['late', 'partial']
            )
            
            # Saldo devedor = soma das parcelas pendentes - valor já pago
            current_balance = sum(
                (inst.amount - inst.amount_paid) for inst in pending_installments
            )
            
            # Dias de atraso (da parcela mais antiga)
            days_overdue = 0
            if overdue_installments:
                oldest_overdue = min(overdue_installments, key=lambda i: i.due_date)
                days_overdue = (fields.Date.today() - oldest_overdue.due_date).days
            
            wizard.current_balance = current_balance
            wizard.overdue_installments_count = len(overdue_installments)
            wizard.pending_installments_count = len(pending_installments)
            wizard.days_overdue = days_overdue
    
    @api.depends('renegotiation_type', 'extension_weeks', 'discount_type', 
                 'discount_percentage', 'discount_amount', 'new_interest_rate', 
                 'new_weeks', 'current_balance')
    def _compute_new_terms(self):
        """Calcula novos termos da renegociação"""
        for wizard in self:
            new_balance = wizard.current_balance
            new_installment_amount = 0
            new_total_weeks = 0
            
            if wizard.renegotiation_type == 'extend':
                # Extensão de prazo - mantém saldo, redistribui
                remaining_installments = wizard.pending_installments_count
                new_total_weeks = remaining_installments + wizard.extension_weeks
                new_installment_amount = new_balance / new_total_weeks if new_total_weeks else 0
                
            elif wizard.renegotiation_type == 'discount':
                # Aplicar desconto
                if wizard.discount_type == 'percentage':
                    discount = new_balance * (wizard.discount_percentage / 100)
                else:
                    discount = wizard.discount_amount
                
                new_balance = max(0, new_balance - discount)
                new_total_weeks = wizard.pending_installments_count
                new_installment_amount = new_balance / new_total_weeks if new_total_weeks else 0
                
            elif wizard.renegotiation_type == 'new_terms':
                # Novos termos completos
                if wizard.new_interest_rate and wizard.new_weeks:
                    # Aplica juros no saldo atual
                    interest_factor = (1 + wizard.new_interest_rate / 100)
                    new_balance = wizard.current_balance * interest_factor
                    new_total_weeks = wizard.new_weeks
                    new_installment_amount = new_balance / new_total_weeks if new_total_weeks else 0
                else:
                    new_total_weeks = wizard.new_weeks or wizard.pending_installments_count
                    new_installment_amount = new_balance / new_total_weeks if new_total_weeks else 0
            
            wizard.new_balance = new_balance
            wizard.new_installment_amount = new_installment_amount
            wizard.new_total_weeks = new_total_weeks
    
    # ===================================
    # VALIDAÇÕES
    # ===================================
    
    @api.constrains('extension_weeks')
    def _check_extension_weeks(self):
        for wizard in self:
            if wizard.renegotiation_type == 'extend' and wizard.extension_weeks <= 0:
                raise ValidationError("Extensão deve ser maior que zero!")
    
    @api.constrains('discount_percentage')
    def _check_discount_percentage(self):
        for wizard in self:
            if (wizard.renegotiation_type == 'discount' and 
                wizard.discount_type == 'percentage' and 
                (wizard.discount_percentage < 0 or wizard.discount_percentage > 100)):
                raise ValidationError("Desconto deve estar entre 0% e 100%!")
    
    @api.constrains('new_weeks')
    def _check_new_weeks(self):
        for wizard in self:
            if wizard.renegotiation_type == 'new_terms' and wizard.new_weeks <= 0:
                raise ValidationError("Novo prazo deve ser maior que zero!")
    
    # ===================================
    # AÇÃO PRINCIPAL
    # ===================================
    
    def action_confirm_renegotiation(self):
        """Confirma a renegociação e executa as mudanças"""
        self.ensure_one()
        
        if self.current_balance <= 0:
            raise UserError("Não há saldo devedor para renegociar!")
        
        if self.overdue_installments_count == 0:
            raise UserError("Não há parcelas atrasadas para renegociar!")
        
        _logger.info(f"Iniciando renegociação de parcelas para empréstimo {self.sale_order_id.name}")
        
        # ================================
        # ETAPA 1: Marcar parcelas antigas como renegociadas
        # ================================
        
        pending_installments = self.sale_order_id.loan_installment_ids.filtered(
            lambda i: i.status in ['pending', 'late', 'partial']
        )
        
        for installment in pending_installments:
            # Força o status para 'renegotiated' sem recalcular
            installment.sudo().write({
                'status': 'renegotiated',
            })
            
            # Log da renegociação
            installment.message_post(
                body=f"🔄 Parcela renegociada em {fields.Date.today().strftime('%d/%m/%Y')}<br/>"
                     f"💰 Saldo na renegociação: {self.currency_id.symbol} {installment.amount - installment.amount_paid:,.2f}<br/>"
                     f"📝 Motivo: {self.notes or 'Renegociação de termos'}"
            )
        
        _logger.info(f"Marcadas {len(pending_installments)} parcelas como renegociadas")
        
        # ================================
        # ETAPA 2: Gerar novas parcelas
        # ================================
        
        installment_obj = self.env['loan.installment']
        due_date = self.renegotiation_start_date + timedelta(days=7)  # Primeira parcela em 1 semana
        
        for i in range(self.new_total_weeks):
            # Pula fins de semana
            while due_date.weekday() in [5, 6]:  # Sábado=5, Domingo=6
                due_date += timedelta(days=1)
            
            installment_data = {
                'sale_order_id': self.sale_order_id.id,
                'number': i + 1,
                'due_date': due_date,
                'amount': self.new_installment_amount,
                'partner_id': self.partner_id.id,
            }
            
            new_installment = installment_obj.create(installment_data)
            
            # Log da criação
            new_installment.message_post(
                body=f"🆕 Nova parcela criada via renegociação<br/>"
                     f"📅 Vencimento: {due_date.strftime('%d/%m/%Y')}<br/>"
                     f"💰 Valor: {self.currency_id.symbol} {self.new_installment_amount:,.2f}<br/>"
                     f"🔢 Parcela {i + 1} de {self.new_total_weeks}"
            )
            
            # Próxima parcela (7 dias depois)
            due_date += timedelta(days=7)
        
        _logger.info(f"Criadas {self.new_total_weeks} novas parcelas")
        
        # ================================
        # ETAPA 3: Atualizar empréstimo
        # ================================
        
        self.sale_order_id.message_post(
            body=f"🔄 <strong>RENEGOCIAÇÃO REALIZADA</strong><br/>"
                 f"📊 Tipo: {dict(self._fields['renegotiation_type'].selection)[self.renegotiation_type]}<br/>"
                 f"💰 Saldo renegociado: {self.currency_id.symbol} {self.current_balance:,.2f}<br/>"
                 f"💳 Novo saldo: {self.currency_id.symbol} {self.new_balance:,.2f}<br/>"
                 f"📅 Novas parcelas: {self.new_total_weeks}x {self.currency_id.symbol} {self.new_installment_amount:,.2f}<br/>"
                 f"📝 Observações: {self.notes or 'Nenhuma'}<br/>"
                 f"👤 Realizada por: {self.env.user.name}"
        )
        
        # Atualiza status se necessário
        if self.sale_order_id.loan_status == 'late':
            self.sale_order_id.loan_status = 'active'
        
        _logger.info(f"Renegociação concluída para empréstimo {self.sale_order_id.name}")
        
        # ================================
        # RETORNO: Abre lista das novas parcelas
        # ================================
        
        return {
            'name': f'Novas Parcelas - {self.sale_order_id.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'loan.installment',
            'view_mode': 'list,form',
            'domain': [
                ('sale_order_id', '=', self.sale_order_id.id),
                ('status', '=', 'pending')
            ],
            'context': {
                'default_sale_order_id': self.sale_order_id.id,
                'search_default_pending': 1,
            },
            'target': 'current',
        }
