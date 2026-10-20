"""Plantilla editable del correo de recuperación de contraseña de Qhub.

Edita libremente el HTML y el asunto. `reset_link` es el enlace a la pantalla del front
({PASSWORD_RESET_URL}/qhub/restablecer?token=...); `ttl_minutos` es la validez del enlace.
"""

from app.infrastructure.delivery.templates.layout import email_layout

PASSWORD_RESET_SUBJECT = "Restablece tu contraseña de Qhub"


def password_reset_html(reset_link: str, ttl_minutos: int) -> str:
    return email_layout(
        title="Restablece tu contraseña",
        body_html="Recibimos una solicitud para restablecer la contraseña de tu cuenta de Qhub. Elige una contraseña nueva con el botón.",
        button=("Elegir contraseña nueva", reset_link),
        note=(
            f"Por seguridad, el enlace vence en {ttl_minutos} minutos y funciona una sola vez.<br><br>"
            f'Si el botón no funciona, copia este enlace en tu navegador:<br><a href="{reset_link}" '
            f'style="color:#3b4eff;word-break:break-all;">{reset_link}</a>'
        ),
    )
