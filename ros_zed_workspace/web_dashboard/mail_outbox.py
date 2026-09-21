#!/usr/bin/env python3
"""Reemplazo local de un servidor de correo: no hay SMTP configurado en este
demo, asi que un "envio de mail" simplemente se escribe a un archivo de
texto (mail_outbox.log) y a stdout, con el mismo contenido que en un uso real
mandaria el correo de aprobacion o de recuperacion de contrasenia."""
import os
import time

OUTBOX_PATH = os.path.join(os.path.dirname(__file__), "mail_outbox.log")


def send(to_email: str, subject: str, body: str, outbox_path=None):
    outbox_path = outbox_path or OUTBOX_PATH
    entry = (
        f"\n----- {time.strftime('%Y-%m-%d %H:%M:%S')} -----\n"
        f"Para: {to_email}\nAsunto: {subject}\n\n{body}\n"
    )
    print(f"[mail simulado] -> {to_email}: {subject}")
    with open(outbox_path, "a", encoding="utf-8") as f:
        f.write(entry)
    return entry
