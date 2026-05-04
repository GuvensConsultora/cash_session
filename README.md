# Cash Session — Cajas con turnos rotativos

Módulo Odoo 19 para operar cajas físicas con apertura, arqueo, cierre y transferencia automática a caja central. **No depende de POS ni de ADHOC cashbox**: vive 100% sobre `account.bank.statement` y `account.payment` nativos.

## Conceptos

- **`cash.register`** — la caja física (multi-journal, multi-usuario, multi-compañía).
- **`cash.session`** — el turno (apertura, operación, cierre).
- **`cash.session.line`** — línea de arqueo por journal y por momento (open/close).

## Flujo del turno

1. **Apertura** — el responsable elige caja, carga el arqueo físico inicial por journal (efectivo, cheques cartera anterior, etc.). Se crean los `account.bank.statement` con `balance_start` igual al arqueo físico.
2. **Operación** — durante el turno, los `account.payment` cuyo journal pertenece a la caja se operan normalmente. Si la caja NO autoriza pagos a proveedores (`allow_payments_out=False`), los outbound se bloquean.
3. **Cierre** — recuento físico de cada rubro. El sistema calcula la diferencia contra el teórico de cada statement.
4. **Validación del cierre**:
   - Si hay diferencia y no hay observación → bloqueo.
   - Postea los statements (Odoo nativo imputa la diferencia a la cuenta configurada en la compañía).
   - Genera el asiento de transferencia a caja central por **efectivo y cheques de terceros** (las tarjetas no se transfieren).

## Configuración

### En cada compañía
- **Cuenta de diferencias de caja** — destino de los faltantes/sobrantes al cerrar.
- **Caja central** — journal destino del asiento de transferencia.

### En cada journal de cash o bank
- **Tipo en caja**: `Efectivo`, `Cheques de terceros`, `Tarjeta`, `No aplica`. Solo los dos primeros se transfieren a caja central al cierre.

### En cada caja física
- **Journals que opera** (m2m).
- **Permite pagos a proveedores** (bool).
- **Responsables autorizados** (m2m users; vacío = todos los del grupo).

## Permisos

- **Cash Session — Usuario**: puede crear y operar sesiones.
- **Cash Session — Manager**: además configura cajas, cuenta de diferencias y caja central.

## Compatibilidad

- Multi-compañía nativo (cada caja, sesión y journal valida `company_id`).
- Constraint: una sola sesión `open` o `closing` por caja en cualquier momento.

## Autor

Yagüven C.G. — 2026
