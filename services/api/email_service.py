"""Correo transaccional con Resend.

La API key viene siempre de la variable de entorno RESEND_API_KEY (ver .env.example).
"""

import logging
from html import escape

import resend

from services.api import config


logger = logging.getLogger("uvicorn.error")


def send_email(to: str, subject: str, html: str, text: str) -> bool:
    """Envía un correo con Resend. Devuelve False (sin lanzar) si no se pudo enviar."""
    if not config.RESEND_API_KEY:
        return False

    resend.api_key = config.RESEND_API_KEY
    try:
        resend.Emails.send(
            {
                "from": config.EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            }
        )
    except Exception:
        # Un fallo del proveedor no debe romper la petición ni revelar nada al cliente.
        logger.exception("No se pudo enviar el correo a %s", to)
        return False
    return True


# =========================================================
# RESTABLECIMIENTO DE CONTRASEÑA
# =========================================================


def _reset_html(link: str, minutes: int) -> str:
    # Una sola columna de ancho fluido (máx. 480px) y estilos en línea: legible en móvil
    # y en clientes de correo que ignoran <style>.
    link = escape(link, quote=True)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Restablece tu contraseña</title>
</head>
<body style="margin:0;padding:0;background:#ecfeff;font-family:Arial,Helvetica,sans-serif;color:#1e293b;">
  <div style="max-width:480px;margin:0 auto;padding:24px 16px;">
    <p style="margin:0 0 16px;font-size:24px;font-weight:800;color:#0e7490;">TrackFlow</p>
    <div style="background:#ffffff;border:1px solid #cffafe;border-radius:16px;padding:24px;">
      <h1 style="margin:0 0 12px;font-size:20px;line-height:1.3;color:#0f172a;">Restablece tu contraseña</h1>
      <p style="margin:0 0 20px;font-size:16px;line-height:1.5;">
        Hemos recibido una solicitud para restablecer la contraseña de tu cuenta.
        Pulsa el botón para elegir una nueva.
      </p>
      <p style="margin:0 0 20px;text-align:center;">
        <a href="{link}" style="display:inline-block;background:#0e7490;color:#ffffff;text-decoration:none;font-size:16px;font-weight:700;padding:14px 24px;border-radius:10px;">
          Restablecer contraseña
        </a>
      </p>
      <p style="margin:0 0 8px;font-size:14px;line-height:1.5;color:#475569;">
        El enlace caduca en {minutes} minutos y solo puede usarse una vez.
      </p>
      <p style="margin:0 0 8px;font-size:14px;line-height:1.5;color:#475569;">
        Si el botón no funciona, copia y pega esta dirección en tu navegador:
      </p>
      <p style="margin:0;font-size:13px;line-height:1.5;word-break:break-all;">
        <a href="{link}" style="color:#0e7490;">{link}</a>
      </p>
    </div>
    <p style="margin:16px 0 0;font-size:13px;line-height:1.5;color:#64748b;">
      Si no has pedido este cambio, ignora este mensaje: tu contraseña seguirá siendo la misma.
    </p>
  </div>
</body>
</html>"""


def _reset_text(link: str, minutes: int) -> str:
    return (
        "Restablece tu contraseña de TrackFlow\n\n"
        "Hemos recibido una solicitud para restablecer la contraseña de tu cuenta. "
        "Abre este enlace para elegir una nueva:\n\n"
        f"{link}\n\n"
        f"El enlace caduca en {minutes} minutos y solo puede usarse una vez.\n"
        "Si no has pedido este cambio, ignora este mensaje."
    )


def send_password_reset_email(to: str, token: str) -> None:
    minutes = config.PASSWORD_RESET_EXPIRE_MINUTES
    link = f"{config.FRONTEND_URL}/reset-password?token={token}"

    if not config.RESEND_API_KEY:
        # Solo desarrollo: sin API key dejamos el enlace en el log para poder probar el flujo.
        logger.warning("RESEND_API_KEY no configurada. Enlace de restablecimiento para %s: %s", to, link)
        return

    send_email(
        to=to,
        subject="Restablece tu contraseña de TrackFlow",
        html=_reset_html(link, minutes),
        text=_reset_text(link, minutes),
    )
