
{
    'name': 'GT Empréstimos - Extensão Vendas',
    'version': '18.0.1.0.0',
    'category': 'Sales', 
    'summary': 'Gestão completa de empréstimos',
    'author': 'GT Empréstimos',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'account', 'product'],
    'data': [
        'data/security_data.xml',
        'data/product_data.xml',
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/loan_installment_views.xml',
        'views/renegotiation_wizard_views.xml', 
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}