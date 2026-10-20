"""Marco común de los correos de Qhub: la misma identidad que los correos de la web (confirmar, invitar, recuperar)."""

_FOOT = "Si no esperabas este correo, ignóralo: no se hará ningún cambio.<br>Qhub · Turnos sin filas"


def email_layout(*, title: str | None, body_html: str, button: tuple[str, str] | None = None, note: str | None = None) -> str:
    title_row = (
        f'<tr><td style="padding:20px 32px 0 32px;font-size:20px;font-weight:600;line-height:28px;">{title}</td></tr>'
        if title else ""
    )
    button_row = (
        f'<tr><td style="padding:24px 32px 0 32px;"><a href="{button[1]}" style="display:inline-block;background:#3b4eff;'
        f'color:#ffffff;text-decoration:none;font-size:15px;font-weight:500;line-height:20px;padding:12px 24px;">{button[0]}</a></td></tr>'
        if button else ""
    )
    note_row = (
        f'<tr><td style="padding:24px 32px 0 32px;font-size:13px;line-height:20px;color:#525252;">{note}</td></tr>'
        if note else ""
    )
    return f"""\
<!doctype html><html lang="es"><body style="margin:0;padding:0;background:#f4f4f4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:32px 16px;"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border:1px solid #e0e0e0;font-family:'IBM Plex Sans',Arial,Helvetica,sans-serif;color:#161616;">
<tr><td style="padding:28px 32px 0 32px;font-size:22px;font-weight:600;letter-spacing:-0.2px;color:#3b4eff;">Qhub</td></tr>
{title_row}
<tr><td style="padding:12px 32px 0 32px;font-size:15px;line-height:24px;color:#525252;">{body_html}</td></tr>
{button_row}
{note_row}
<tr><td style="padding:24px 32px 28px 32px;"><div style="border-top:1px solid #e0e0e0;padding-top:16px;font-size:12px;line-height:18px;color:#525252;">{_FOOT}</div></td></tr>
</table></td></tr></table></body></html>
"""
