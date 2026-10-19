"""Plantilla editable del correo de recuperación de contraseña de Qhub.

Edita libremente el HTML y el asunto. `reset_link` es el enlace a la pantalla del front
({PASSWORD_RESET_URL}/qhub/restablecer?token=...); `ttl_minutos` es la validez del enlace.
"""

PASSWORD_RESET_SUBJECT = "Recupera tu contraseña de Qhub"


def password_reset_html(reset_link: str, ttl_minutos: int) -> str:
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
              <td style="font-size:18px;font-weight:bold;padding-bottom:12px;">
                Recupera tu contraseña
              </td>
            </tr>
            <tr>
              <td style="font-size:14px;line-height:22px;padding-bottom:24px;">
                Recibimos una solicitud para restablecer la contraseña de tu cuenta de Qhub.
                Haz clic en el botón para elegir una contraseña nueva. Si no lo solicitaste,
                puedes ignorar este correo.
              </td>
            </tr>
            <tr>
              <td align="center" style="padding-bottom:24px;">
                <a href="{reset_link}"
                   style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;
                          padding:12px 24px;border-radius:8px;font-size:15px;font-weight:bold;">
                  Elegir contraseña nueva
                </a>
              </td>
            </tr>
            <tr>
              <td style="font-size:12px;line-height:18px;color:#6b7280;padding-bottom:12px;">
                El enlace vence en {ttl_minutos} minutos. Si expira, solicita uno nuevo desde
                la pantalla de recuperación.
              </td>
            </tr>
            <tr>
              <td style="font-size:12px;line-height:18px;color:#6b7280;">
                Si el botón no funciona, copia y pega este enlace en tu navegador:<br />
                <a href="{reset_link}" style="color:#4f46e5;word-break:break-all;">{reset_link}</a>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
