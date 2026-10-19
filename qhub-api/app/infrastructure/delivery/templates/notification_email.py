"""Plantilla editable de los correos de aviso de turno de Qhub.

Edita libremente el HTML y los asuntos. El cuerpo reutiliza el texto del aviso
(`notification.mensaje`); `subject_for` devuelve el asunto por tipo de aviso o `None`
cuando el tipo no debe enviar correo (y el canal lo omite)."""

# Asuntos por tipo de aviso "importante" para el cliente. Solo estos tipos envían correo;
# cualquier otro (p. ej. "turno_pospuesto", que es solo en vivo) no está aquí y se omite.
_SUBJECTS: dict[str, str] = {
    "recordatorio": "Qhub · Recordatorio de tu turno",
    "turno_llamado": "Qhub · Están atendiendo tu turno",
    "turno_no_show": "Qhub · Tu turno no se presentó",
    "turno_cancelado": "Qhub · Tu turno fue cancelado",
}


def subject_for(notice_type: str) -> str | None:
    """Asunto del correo para este tipo de aviso, o `None` si el tipo no envía correo."""
    return _SUBJECTS.get(notice_type)


def notification_email_html(message: str) -> str:
    """HTML mínimo con marca Qhub; el cuerpo reutiliza el texto del aviso."""
    return f"""\
<!doctype html>
<html lang="es">
  <body style="margin:0;padding:0;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;color:#1f2937;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;padding:32px;">
            <tr>
              <td align="center" style="padding-bottom:16px;">
                <span style="font-size:24px;font-weight:bold;color:#4f46e5;">Qhub</span>
              </td>
            </tr>
            <tr>
              <td style="font-size:15px;line-height:24px;">
                {message}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
