{
    'name': 'Caja — Sesiones con turnos rotativos',
    'version': '19.0.2.4.1',
    'category': 'Caja',
    'summary': 'Operación de cajas físicas con apertura/arqueo/cierre y '
               'transferencia automática a caja central. Multi-compañía, '
               'multi-caja, multi-turno. Aplicación independiente con menús '
               'propios y ayuda integrada.',
    'description': """
Módulo custom sobre lo nativo de Odoo (account.bank.statement + account.payment).
NO usa POS ni stack ADHOC cashbox.

Provee tres modelos centrales:
- cash.register: configuración de la caja física (multi-journal, multi-usuario).
- cash.session: el turno (apertura, operación, cierre, transferencia).
- cash.session.line: líneas de arqueo por journal (open/close).

Y un modelo de ayuda integrada:
- cash.session.help: FAQ y guías "Cómo funciona" accesibles desde el menú.

Características:
- Aplicación independiente con menú propio (no anidada en Facturación).
- Multi-compañía con cuenta de diferencias y caja central configurables.
- Permite o bloquea pagos a proveedores desde la caja según cash_register.allow_payments_out.
- Una sola sesión OPEN por caja (constraint).
- Cierre con diferencia permitido con observaciones obligatorias.
- Transferencia automática al cierre: solo efectivo a caja central
  (cheques de terceros quedan en la cartera de la compañía).
- Documentación in-app: FAQ y guías paso a paso.
    """,
    'author': 'Yagüven C.G.',
    'website': 'https://yaguven.com.ar',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_latam_check'],
    'data': [
        'security/cash_session_groups.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/cash_session_help_data.xml',
        'views/res_company_views.xml',
        'views/account_journal_views.xml',
        'views/cash_register_views.xml',
        'views/cash_session_views.xml',
        'views/cash_session_help_views.xml',
        'views/menus.xml',
        'report/cash_session_handover_report.xml',
    ],
    'installable': True,
    'application': True,
}
