# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class LoanInstallment(models.Model):
    _name = 'loan.installment'
    _description = 'Parcela de Empréstimo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sale_order_id, number'
    _rec_name = 'display_name'
    
    display_name = fields.Char(
        string='Nome',
        compute='_compute_display_name',
        store=True
    )
    
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Ordem de Venda',
        required=True,
        ondelete='cascade'
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        required=True
    )
    
    number = fields.Integer(
        string='Nº Parcela',
        required=True
    )
    
    due_date = fields.Date(
        string='Data de Vencimento',
        required=True
    )
    
    amount = fields.Monetary(
        string='Valor da Parcela',
        currency_field='currency_id',
        required=True
    )
    
    amount_paid = fields.Monetary(
        string='Valor Pago',
        currency_field='currency_id',
        default=0.0
    )
    
    payment_date = fields.Date(
        string='Data de Pagamento'
    )
    
    status = fields.Selection([
        ('pending', 'Pendente'),
        ('paid', 'Pago'),
        ('late', 'Atrasado'),
        ('partial', 'Parcialmente Pago')
    ], string='Status', default='pending', compute='_compute_status', store=True)
    
    currency_id = fields.Many2one(
        'res.currency',
        related='sale_order_id.currency_id',
        string='Moeda',
        store=True
    )
    
    days_late = fields.Integer(
        string='Dias em Atraso',
        compute='_compute_days_late'
    )
    
    # CAMPOS PARA FATURAMENTO INDIVIDUAL
    invoice_id = fields.Many2one(
        'account.move', 
        string='Fatura Individual', 
        readonly=True,
        help='Fatura específica desta parcela'
    )
    
    invoice_state = fields.Selection(
        related='invoice_id.state', 
        string='Status da Fatura'
    )
    
    can_generate_invoice = fields.Boolean(
        string='Pode Gerar Fatura', 
        compute='_compute_can_generate_invoice'
    )
    
    @api.depends('sale_order_id.name', 'number')
    def _compute_display_name(self):
        for rec in self:
            if rec.sale_order_id and rec.sale_order_id.name:
                rec.display_name = f"{rec.sale_order_id.name} - Parcela {rec.number}"
            else:
                rec.display_name = f"Parcela {rec.number}"
    
    @api.depends('due_date', 'amount', 'amount_paid')
    def _compute_status(self):
        today = fields.Date.today()
        for rec in self:
            if rec.amount_paid >= rec.amount:
                rec.status = 'paid'
            elif rec.amount_paid > 0:
                rec.status = 'partial'
            elif rec.due_date and rec.due_date < today:
                rec.status = 'late'
            else:
                rec.status = 'pending'
    
    @api.depends('due_date', 'status')
    def _compute_days_late(self):
        today = fields.Date.today()
        for rec in self:
            if rec.status in ['late', 'partial'] and rec.due_date:
                rec.days_late = (today - rec.due_date).days
            else:
                rec.days_late = 0
    
    @api.depends('status', 'invoice_id')
    def _compute_can_generate_invoice(self):
        """Determina se pode gerar fatura individual"""
        for installment in self:
            installment.can_generate_invoice = (
                installment.status in ['pending', 'late', 'partial'] and 
                not installment.invoice_id
            )
    
    def action_register_payment(self):
        """Registra pagamento total da parcela (MÉTODO ORIGINAL MANTIDO)"""
        for rec in self:
            rec.write({
                'amount_paid': rec.amount,
                'payment_date': fields.Date.today(),
            })
            
            # Log do pagamento
            rec.message_post(
                body=f"💰 Pagamento integral registrado: {rec.currency_id.symbol} {rec.amount:,.2f}"
            )
        return True
    
    # ========================================
    # FUNCIONALIDADE CORRIGIDA: FATURAMENTO INDIVIDUAL
    # ========================================
    
    def action_generate_invoice(self):
        """Gera fatura individual para a parcela COM VALOR CORRETO DA PARCELA"""
        for installment in self:
            if installment.invoice_id:
                raise UserError(f"Parcela {installment.number} já possui fatura gerada!")
            
            if installment.status == 'paid':
                raise UserError(f"Não é possível gerar fatura para parcela já paga!")
            
            _logger.info(f"Gerando fatura individual para parcela {installment.number} do pedido {installment.sale_order_id.name}")
            
            # Busca o produto de empréstimo
            loan_products = self.env['product.product'].search([
                ('is_loan_product', '=', True)
            ], limit=1)
            
            if not loan_products:
                raise UserError("Nenhum produto de empréstimo encontrado! Configure um produto com 'É Produto de Empréstimo' marcado.")
            
            loan_product = loan_products[0]
            
            # ============================================
            # CORREÇÃO: VALOR DA PARCELA, NÃO DO TOTAL
            # ============================================
            
            # Valor a faturar = valor da parcela - valor já pago
            amount_to_invoice = installment.amount - installment.amount_paid
            
            if amount_to_invoice <= 0:
                raise UserError("Não há valor pendente para faturar nesta parcela!")
            
            _logger.info(f"Faturando parcela {installment.number}: Valor da parcela = ${installment.amount:.2f}, Já pago = ${installment.amount_paid:.2f}, A faturar = ${amount_to_invoice:.2f}")
            
            # Dados da fatura individual
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': installment.partner_id.id,
                'invoice_date': fields.Date.today(),
                'invoice_date_due': installment.due_date,
                'currency_id': installment.currency_id.id,
                'invoice_origin': f"{installment.sale_order_id.name} - Parcela {installment.number}",
                'ref': f"Parcela {installment.number}/{installment.sale_order_id.loan_weeks}",
                'invoice_line_ids': [(0, 0, {
                    'product_id': loan_product.id,
                    'name': f"Empréstimo - Parcela {installment.number}/{installment.sale_order_id.loan_weeks} - Venc: {installment.due_date.strftime('%d/%m/%Y')}",
                    'quantity': 1,
                    # ===========================
                    # CORREÇÃO PRINCIPAL AQUI:
                    # ===========================
                    'price_unit': amount_to_invoice,  # Valor da parcela, não do total!
                    'tax_ids': [(6, 0, loan_product.taxes_id.ids)],
                })],
            }
            
            # Cria a fatura
            invoice = self.env['account.move'].create(invoice_vals)
            
            # Vincula a fatura à parcela
            installment.write({
                'invoice_id': invoice.id,
            })
            
            # Log da criação
            installment.message_post(
                body=f"📄 Fatura individual gerada: {invoice.name}<br/>"
                     f"💰 Valor faturado: {installment.currency_id.symbol} {amount_to_invoice:,.2f}<br/>"
                     f"📅 Vencimento: {installment.due_date.strftime('%d/%m/%Y')}<br/>"
                     f"📋 Parcela {installment.number} de {installment.sale_order_id.loan_weeks}"
            )
            
            _logger.info(f"Fatura individual {invoice.name} criada com sucesso para parcela {installment.number} - Valor: ${amount_to_invoice:.2f}")
            
            # Retorna ação para abrir a fatura
            return {
                'name': f'Fatura - Parcela {installment.number}',
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': invoice.id,
                'view_mode': 'form',
                'target': 'current',
            }
        
        return True

    def action_view_invoice(self):
        """Abre a fatura da parcela"""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError("Esta parcela não possui fatura gerada!")
        
        return {
            'name': f'Fatura - Parcela {self.number}',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_register_partial_payment(self):
        """Abre wizard para registrar pagamento parcial"""
        self.ensure_one()
        
        remaining_amount = self.amount - self.amount_paid
        if remaining_amount <= 0:
            raise UserError("Esta parcela já está totalmente paga!")
        
        return {
            'name': f'Registrar Pagamento - Parcela {self.number}',
            'type': 'ir.actions.act_window',
            'res_model': 'loan.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_installment_id': self.id,
                'default_amount': remaining_amount,
                'default_max_amount': remaining_amount,
            }
        }

    def action_cancel_invoice(self):
        """Cancela a fatura da parcela"""
        self.ensure_one()
        if not self.invoice_id:
            raise UserError("Esta parcela não possui fatura!")
        
        if self.invoice_id.state == 'posted' and self.invoice_id.payment_state == 'paid':
            raise UserError("Não é possível cancelar fatura já paga!")
        
        invoice_name = self.invoice_id.name
        invoice_amount = self.invoice_id.amount_total
        
        # Cancela a fatura
        if self.invoice_id.state == 'posted':
            self.invoice_id.button_cancel()
        
        self.invoice_id.button_draft()
        self.invoice_id.unlink()
        
        self.write({
            'invoice_id': False
        })
        
        # Log do cancelamento
        self.message_post(
            body=f"❌ Fatura {invoice_name} cancelada e removida da parcela {self.number}<br/>"
                 f"💰 Valor cancelado: {self.currency_id.symbol} {invoice_amount:,.2f}"
        )
        
        return True
    
    # ========================================
    # AUTOMAÇÃO DE PAGAMENTOS VIA FATURAS
    # ========================================
    
    @api.model
    def _check_invoice_payments(self):
        """Verifica faturas pagas e atualiza status das parcelas automaticamente"""
        paid_invoices = self.env['account.move'].search([
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['paid', 'in_payment']),
            ('move_type', '=', 'out_invoice'),
            ('invoice_origin', 'like', '%Parcela%')
        ])
        
        updated_count = 0
        for invoice in paid_invoices:
            installments = self.search([
                ('invoice_id', '=', invoice.id),
                ('status', '!=', 'paid')
            ])
            
            for installment in installments:
                # Valor pago é o valor da fatura paga
                paid_amount = invoice.amount_total
                total_paid = installment.amount_paid + paid_amount
                
                # Não pode pagar mais que o valor da parcela
                final_paid = min(total_paid, installment.amount)
                
                installment.write({
                    'amount_paid': final_paid,
                    'payment_date': fields.Date.today() if final_paid >= installment.amount else installment.payment_date
                })
                
                # Log da atualização automática
                installment.message_post(
                    body=f"🔄 Status atualizado automaticamente via fatura {invoice.name}<br/>"
                         f"💰 Valor pago: {installment.currency_id.symbol} {paid_amount:,.2f}<br/>"
                         f"📊 Total pago na parcela: {installment.currency_id.symbol} {final_paid:,.2f}"
                )
                
                updated_count += 1
                _logger.info(f"Parcela {installment.number} atualizada automaticamente via fatura {invoice.name} - Valor: ${paid_amount:.2f}")
        
        if updated_count > 0:
            _logger.info(f"Automação de pagamentos concluída: {updated_count} parcelas atualizadas")
    
    # ========================================
    # VALIDAÇÕES E CONSTRAINTS
    # ========================================
    
    @api.constrains('amount_paid', 'amount')
    def _check_amount_paid(self):
        """Valida se valor pago não é maior que valor da parcela"""
        for rec in self:
            if rec.amount_paid > rec.amount:
                raise ValidationError(f"Valor pago (${rec.amount_paid:.2f}) não pode ser maior que o valor da parcela (${rec.amount:.2f})")

    @api.constrains('due_date')
    def _check_due_date(self):
        """Valida data de vencimento"""
        for rec in self:
            if rec.due_date and rec.sale_order_id.loan_start_date:
                if rec.due_date <= rec.sale_order_id.loan_start_date:
                    raise ValidationError("Data de vencimento deve ser posterior à data de início do empréstimo")

    def name_get(self):
        """Nome personalizado para parcelas"""
        result = []
        for installment in self:
            name = f"Parcela {installment.number}"
            if installment.sale_order_id:
                name += f" - {installment.sale_order_id.name}"
            if installment.amount:
                name += f" (${installment.amount:.2f})"
            if installment.status == 'late':
                name += f" ⚠️ {installment.days_late} dias"
            elif installment.status == 'paid':
                name += " ✅"
                
            result.append((installment.id, name))
        return result