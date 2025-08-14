# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class LoanInstallment(models.Model):
    _name = 'loan.installment'
    _description = 'Parcela de EmprÃ©stimo'
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
        string='NÂº Parcela',
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
        ('partial', 'Parcialmente Pago'),
        ('renegotiated', 'Renegociado')
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
        help='Fatura especÃ­fica desta parcela'
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
        """Registra pagamento total da parcela (MÃ‰TODO ORIGINAL MANTIDO)"""
        for rec in self:
            rec.write({
                'amount_paid': rec.amount,
                'payment_date': fields.Date.today(),
            })
            
            # Log do pagamento
            rec.message_post(
                body=f"ðŸ'° Pagamento integral registrado: {rec.currency_id.symbol} {rec.amount:,.2f}"
            )
        return True
    
    # ========================================
    # NOVA FUNCIONALIDADE: FATURAMENTO EM LOTE
    # ========================================
    
    def action_generate_batch_invoice(self):
        """Gera uma única fatura para múltiplas parcelas selecionadas"""
        
        # Validações iniciais
        if not self:
            raise UserError("Nenhuma parcela selecionada!")
        
        # Verifica se todas as parcelas são do mesmo cliente
        partners = self.mapped('partner_id')
        if len(partners) > 1:
            partner_names = ', '.join(partners.mapped('name'))
            raise UserError(f"Não é possível gerar fatura para clientes diferentes!\nClientes: {partner_names}")
        
        partner = partners[0]
        
        # Verifica se alguma parcela já possui fatura
        with_invoice = self.filtered('invoice_id')
        if with_invoice:
            installment_numbers = ', '.join([str(i.number) for i in with_invoice])
            raise UserError(f"As seguintes parcelas já possuem faturas: {installment_numbers}")
        
        # Verifica se há parcelas pagas
        paid_installments = self.filtered(lambda i: i.status == 'paid')
        if paid_installments:
            paid_numbers = ', '.join([str(i.number) for i in paid_installments])
            raise UserError(f"Não é possível faturar parcelas já pagas: {paid_numbers}")
        
        _logger.info(f"Gerando fatura em lote para {len(self)} parcelas do cliente {partner.name}")
        
        # Busca o produto de empréstimo
        loan_products = self.env['product.product'].search([
            ('is_loan_product', '=', True)
        ], limit=1)
        
        if not loan_products:
            raise UserError("Nenhum produto de empréstimo encontrado! Configure um produto com 'É Produto de Empréstimo' marcado.")
        
        loan_product = loan_products[0]
        
        # Calcula valores totais
        total_amount = sum((inst.amount - inst.amount_paid) for inst in self)
        installment_count = len(self)
        
        if total_amount <= 0:
            raise UserError("Não há valor pendente para faturar nas parcelas selecionadas!")
        
        # Determina as datas
        earliest_due_date = min(self.mapped('due_date'))
        latest_due_date = max(self.mapped('due_date'))
        
        # Prepara lista de parcelas para descrição
        installment_numbers = sorted([inst.number for inst in self])
        if len(installment_numbers) > 5:
            installments_desc = f"{installment_numbers[0]} a {installment_numbers[-1]}"
        else:
            installments_desc = ', '.join([str(n) for n in installment_numbers])
        
        # Agrupa por empréstimo para a descrição
        orders = self.mapped('sale_order_id')
        if len(orders) == 1:
            order_desc = orders[0].name
        else:
            order_desc = f"{len(orders)} empréstimos"
        
        # Cria linhas da fatura agrupadas ou detalhadas
        invoice_lines = []
        
        if len(self) <= 10:  # Se poucas parcelas, detalha cada uma
            for installment in self.sorted('number'):
                amount_to_invoice = installment.amount - installment.amount_paid
                if amount_to_invoice > 0:
                    invoice_lines.append((0, 0, {
                        'product_id': loan_product.id,
                        'name': f"Parcela {installment.number} - Empréstimo {installment.sale_order_id.name} - Venc: {installment.due_date.strftime('%d/%m/%Y')}",
                        'quantity': 1,
                        'price_unit': amount_to_invoice,
                        'tax_ids': [(6, 0, loan_product.taxes_id.ids)],
                    }))
        else:  # Se muitas parcelas, agrupa em uma linha
            invoice_lines.append((0, 0, {
                'product_id': loan_product.id,
                'name': f"Faturamento em Lote - {installment_count} parcelas\nParcelas: {installments_desc}\nEmpréstimo(s): {order_desc}\nVencimentos: {earliest_due_date.strftime('%d/%m/%Y')} a {latest_due_date.strftime('%d/%m/%Y')}",
                'quantity': installment_count,
                'price_unit': total_amount / installment_count,
                'tax_ids': [(6, 0, loan_product.taxes_id.ids)],
            }))
        
        # Dados da fatura consolidada
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': fields.Date.today(),
            'invoice_date_due': earliest_due_date,  # Usa a data mais próxima
            'currency_id': self[0].currency_id.id,
            'invoice_origin': f"Faturamento em Lote - {order_desc}",
            'ref': f"Lote: {installment_count} parcelas",
            'invoice_line_ids': invoice_lines,
        }
        
        # Cria a fatura
        invoice = self.env['account.move'].create(invoice_vals)
        
        # Vincula todas as parcelas à fatura
        self.write({
            'invoice_id': invoice.id,
        })
        
        # Log individual em cada parcela
        for installment in self:
            amount_invoiced = installment.amount - installment.amount_paid
            installment.message_post(
                body=f"📄 **Fatura em Lote:** {invoice.name}<br/>"
                     f"💰 Valor desta parcela: {installment.currency_id.symbol} {amount_invoiced:,.2f}<br/>"
                     f"📊 Total da fatura: {installment.currency_id.symbol} {total_amount:,.2f}<br/>"
                     f"🔢 Parcelas incluídas: {installment_count}<br/>"
                     f"👥 Cliente: {partner.name}"
            )
        
        # Log detalhado no sistema
        _logger.info(f"Fatura em lote {invoice.name} criada com sucesso:")
        _logger.info(f"- Cliente: {partner.name}")
        _logger.info(f"- Parcelas: {installment_numbers}")
        _logger.info(f"- Valor total: {total_amount:.2f}")
        _logger.info(f"- Empréstimos: {[o.name for o in orders]}")
        
        # Retorna ação para abrir a fatura
        return {
            'name': f'Fatura em Lote - {installment_count} Parcelas',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_move_type': 'out_invoice',
            }
        }
    
    # ========================================
    # FUNCIONALIDADE ORIGINAL: FATURAMENTO INDIVIDUAL
    # ========================================
    
    def action_generate_invoice(self):
        """Gera fatura individual para a parcela COM VALOR CORRETO DA PARCELA"""
        for installment in self:
            if installment.invoice_id:
                raise UserError(f"Parcela {installment.number} jÃ¡ possui fatura gerada!")
            
            if installment.status == 'paid':
                raise UserError(f"NÃ£o Ã© possÃ­vel gerar fatura para parcela jÃ¡ paga!")
            
            _logger.info(f"Gerando fatura individual para parcela {installment.number} do pedido {installment.sale_order_id.name}")
            
            # Busca o produto de emprÃ©stimo
            loan_products = self.env['product.product'].search([
                ('is_loan_product', '=', True)
            ], limit=1)
            
            if not loan_products:
                raise UserError("Nenhum produto de emprÃ©stimo encontrado! Configure um produto com 'Ã‰ Produto de EmprÃ©stimo' marcado.")
            
            loan_product = loan_products[0]
            
            # Valor a faturar = valor da parcela - valor jÃ¡ pago
            amount_to_invoice = installment.amount - installment.amount_paid
            
            if amount_to_invoice <= 0:
                raise UserError("NÃ£o hÃ¡ valor pendente para faturar nesta parcela!")
            
            _logger.info(f"Faturando parcela {installment.number}: Valor da parcela = ${installment.amount:.2f}, JÃ¡ pago = ${installment.amount_paid:.2f}, A faturar = ${amount_to_invoice:.2f}")
            
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
                    'name': f"EmprÃ©stimo - Parcela {installment.number}/{installment.sale_order_id.loan_weeks} - Venc: {installment.due_date.strftime('%d/%m/%Y')}",
                    'quantity': 1,
                    'price_unit': amount_to_invoice,
                    'tax_ids': [(6, 0, loan_product.taxes_id.ids)],
                })],
            }
            
            # Cria a fatura
            invoice = self.env['account.move'].create(invoice_vals)
            
            # Vincula a fatura Ã  parcela
            installment.write({
                'invoice_id': invoice.id,
            })
            
            # Log da criaÃ§Ã£o
            installment.message_post(
                body=f"ðŸ"„ Fatura individual gerada: {invoice.name}<br/>"
                     f"ðŸ'° Valor faturado: {installment.currency_id.symbol} {amount_to_invoice:,.2f}<br/>"
                     f"ðŸ"… Vencimento: {installment.due_date.strftime('%d/%m/%Y')}<br/>"
                     f"ðŸ"‹ Parcela {installment.number} de {installment.sale_order_id.loan_weeks}"
            )
            
            _logger.info(f"Fatura individual {invoice.name} criada com sucesso para parcela {installment.number} - Valor: ${amount_to_invoice:.2f}")
            
            # Retorna aÃ§Ã£o para abrir a fatura
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
            raise UserError("Esta parcela nÃ£o possui fatura gerada!")
        
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
            raise UserError("Esta parcela jÃ¡ estÃ¡ totalmente paga!")
        
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
            raise UserError("Esta parcela nÃ£o possui fatura!")
        
        if self.invoice_id.state == 'posted' and self.invoice_id.payment_state == 'paid':
            raise UserError("NÃ£o Ã© possÃ­vel cancelar fatura jÃ¡ paga!")
        
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
            body=f"âŒ Fatura {invoice_name} cancelada e removida da parcela {self.number}<br/>"
                 f"ðŸ'° Valor cancelado: {self.currency_id.symbol} {invoice_amount:,.2f}"
        )
        
        return True
    
    # ========================================
    # AUTOMAÃ‡ÃƒO DE PAGAMENTOS VIA FATURAS
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
                # Valor pago Ã© o valor da fatura paga
                paid_amount = invoice.amount_total
                total_paid = installment.amount_paid + paid_amount
                
                # NÃ£o pode pagar mais que o valor da parcela
                final_paid = min(total_paid, installment.amount)
                
                installment.write({
                    'amount_paid': final_paid,
                    'payment_date': fields.Date.today() if final_paid >= installment.amount else installment.payment_date
                })
                
                # Log da atualizaÃ§Ã£o automÃ¡tica
                installment.message_post(
                    body=f"ðŸ"„ Status atualizado automaticamente via fatura {invoice.name}<br/>"
                         f"ðŸ'° Valor pago: {installment.currency_id.symbol} {paid_amount:,.2f}<br/>"
                         f"ðŸ"Š Total pago na parcela: {installment.currency_id.symbol} {final_paid:,.2f}"
                )
                
                updated_count += 1
                _logger.info(f"Parcela {installment.number} atualizada automaticamente via fatura {invoice.name} - Valor: ${paid_amount:.2f}")
        
        if updated_count > 0:
            _logger.info(f"AutomaÃ§Ã£o de pagamentos concluÃ­da: {updated_count} parcelas atualizadas")
    
    # ========================================
    # VALIDAÃ‡Ã•ES E CONSTRAINTS
    # ========================================
    
    @api.constrains('amount_paid', 'amount')
    def _check_amount_paid(self):
        """Valida se valor pago nÃ£o Ã© maior que valor da parcela"""
        for rec in self:
            if rec.amount_paid > rec.amount:
                raise ValidationError(f"Valor pago (${rec.amount_paid:.2f}) nÃ£o pode ser maior que o valor da parcela (${rec.amount:.2f})")

    @api.constrains('due_date')
    def _check_due_date(self):
        """Valida data de vencimento"""
        for rec in self:
            if rec.due_date and rec.sale_order_id.loan_start_date:
                if rec.due_date <= rec.sale_order_id.loan_start_date:
                    raise ValidationError("Data de vencimento deve ser posterior Ã  data de inÃ­cio do emprÃ©stimo")

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
                name += f" âš ï¸ {installment.days_late} dias"
            elif installment.status == 'paid':
                name += " âœ…"
                
            result.append((installment.id, name))
        return result
