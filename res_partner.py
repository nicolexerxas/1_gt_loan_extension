# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError
import re

class ResPartner(models.Model):
    _inherit = 'res.partner'
    
    # Campos para CPF e CNPJ (se não existirem)
    cpf = fields.Char(
        string='CPF',
        size=14,
        help='CPF do contato'
    )
    
    cnpj = fields.Char(
        string='CNPJ', 
        size=18,
        help='CNPJ do contato'
    )
    
    # Campo para mostrar se é válido
    cpf_valid = fields.Boolean(
        string='CPF Válido',
        compute='_compute_cpf_valid',
        store=True
    )
    
    cnpj_valid = fields.Boolean(
        string='CNPJ Válido',
        compute='_compute_cnpj_valid',
        store=True
    )
    
    @api.depends('cpf')
    def _compute_cpf_valid(self):
        for partner in self:
            partner.cpf_valid = self._validate_cpf(partner.cpf) if partner.cpf else False
    
    @api.depends('cnpj')
    def _compute_cnpj_valid(self):
        for partner in self:
            partner.cnpj_valid = self._validate_cnpj(partner.cnpj) if partner.cnpj else False
    
    def _clean_document(self, document):
        """Remove caracteres especiais do documento"""
        if not document:
            return ''
        return re.sub(r'[^0-9]', '', document)
    
    def _validate_cpf(self, cpf):
        """Valida CPF usando algoritmo oficial"""
        if not cpf:
            return False
            
        # Remove caracteres especiais
        cpf = self._clean_document(cpf)
        
        # Verifica se tem 11 dígitos
        if len(cpf) != 11:
            return False
        
        # Verifica se não são todos iguais
        if cpf == cpf[0] * 11:
            return False
        
        # Cálculo do primeiro dígito verificador
        soma = 0
        for i in range(9):
            soma += int(cpf[i]) * (10 - i)
        
        primeiro_digito = 11 - (soma % 11)
        if primeiro_digito >= 10:
            primeiro_digito = 0
        
        if int(cpf[9]) != primeiro_digito:
            return False
        
        # Cálculo do segundo dígito verificador
        soma = 0
        for i in range(10):
            soma += int(cpf[i]) * (11 - i)
        
        segundo_digito = 11 - (soma % 11)
        if segundo_digito >= 10:
            segundo_digito = 0
        
        return int(cpf[10]) == segundo_digito
    
    def _validate_cnpj(self, cnpj):
        """Valida CNPJ usando algoritmo oficial"""
        if not cnpj:
            return False
            
        # Remove caracteres especiais
        cnpj = self._clean_document(cnpj)
        
        # Verifica se tem 14 dígitos
        if len(cnpj) != 14:
            return False
        
        # Verifica se não são todos iguais
        if cnpj == cnpj[0] * 14:
            return False
        
        # Cálculo do primeiro dígito verificador
        multiplicadores1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = 0
        for i in range(12):
            soma += int(cnpj[i]) * multiplicadores1[i]
        
        primeiro_digito = 11 - (soma % 11)
        if primeiro_digito >= 10:
            primeiro_digito = 0
        
        if int(cnpj[12]) != primeiro_digito:
            return False
        
        # Cálculo do segundo dígito verificador
        multiplicadores2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = 0
        for i in range(13):
            soma += int(cnpj[i]) * multiplicadores2[i]
        
        segundo_digito = 11 - (soma % 11)
        if segundo_digito >= 10:
            segundo_digito = 0
        
        return int(cnpj[13]) == segundo_digito
    
    @api.onchange('cpf')
    def _onchange_cpf(self):
        """Formata CPF e valida em tempo real"""
        if self.cpf:
            # Remove caracteres especiais
            cpf_clean = self._clean_document(self.cpf)
            
            # Formata CPF (000.000.000-00)
            if len(cpf_clean) == 11:
                self.cpf = f"{cpf_clean[:3]}.{cpf_clean[3:6]}.{cpf_clean[6:9]}-{cpf_clean[9:]}"
            
            # Valida
            if not self._validate_cpf(self.cpf):
                return {
                    'warning': {
                        'title': 'CPF Inválido',
                        'message': 'O CPF informado não é válido. Verifique os números digitados.'
                    }
                }
    
    @api.onchange('cnpj')
    def _onchange_cnpj(self):
        """Formata CNPJ e valida em tempo real"""
        if self.cnpj:
            # Remove caracteres especiais
            cnpj_clean = self._clean_document(self.cnpj)
            
            # Formata CNPJ (00.000.000/0000-00)
            if len(cnpj_clean) == 14:
                self.cnpj = f"{cnpj_clean[:2]}.{cnpj_clean[2:5]}.{cnpj_clean[5:8]}/{cnpj_clean[8:12]}-{cnpj_clean[12:]}"
            
            # Valida
            if not self._validate_cnpj(self.cnpj):
                return {
                    'warning': {
                        'title': 'CNPJ Inválido', 
                        'message': 'O CNPJ informado não é válido. Verifique os números digitados.'
                    }
                }
    
    @api.constrains('cpf')
    def _check_cpf(self):
        """Validação obrigatória no salvamento"""
        for partner in self:
            if partner.cpf and not self._validate_cpf(partner.cpf):
                raise ValidationError('CPF inválido: %s' % partner.cpf)
    
    @api.constrains('cnpj')
    def _check_cnpj(self):
        """Validação obrigatória no salvamento"""
        for partner in self:
            if partner.cnpj and not self._validate_cnpj(partner.cnpj):
                raise ValidationError('CNPJ inválido: %s' % partner.cnpj)
