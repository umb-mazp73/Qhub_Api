"""Plantilla editable de los correos de aviso de turno de Qhub.

Edita libremente el HTML y los asuntos. El cuerpo reutiliza el texto del aviso
(`notification.mensaje`); `subject_for` devuelve el asunto por tipo de aviso o `None`
cuando el tipo no debe enviar correo (y el canal lo omite)."""

from app.infrastructure.delivery.templates.layout import email_layout

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
    """Correo con la identidad de Qhub; el cuerpo reutiliza el texto del aviso."""
    return email_layout(title=None, body_html=message)
