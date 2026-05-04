{
    'name': 'Cash Session — Cajas con turnos rotativos',
    'version': '19.0.1.0.2',
    'category': 'Accounting',
    'summary': 'Sesiones de caja con apertura/arqueo/cierre y transferencia '
               'automática a caja central. Multi-compañía, multi-caja, multi-turno.',
    'description': """
Módulo custom sobre lo nativo de Odoo (account.bank.statement + account.payment).
NO usa POS ni stack ADHOC cashbox.

Provee tres modelos:
- cash.register: configuración de la caja física (multi-journal, multi-usuario).
- cash.session: el turno (apertura, operación, cierre, transferencia).
- cash.session.line: líneas de arqueo por journal (open/close).

Características:
- Multi-compañía con cuenta de diferencias y caja central configurables por company.
- Permite o bloquea pagos a proveedores desde la caja según cash_register.allow_payments_out.
- Una sola sesión OPEN por caja (constraint).
- Cierre con diferencia permitido con observaciones obligatorias.
- Transferencia automática al cierre: efectivo + cheques de terceros a caja central.
    """,
    'author': 'Yagüven C.G.',
    'website': 'https://yaguven.com.ar',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/cash_session_groups.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'views/res_company_views.xml',
        'views/account_journal_views.xml',
        'views/cash_register_views.xml',
        'views/cash_session_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
