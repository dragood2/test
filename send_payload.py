#!/usr/bin/env python3
"""
send_payload.py -- Envoie un fichier .js a la PS5.
Equivalent de Y2JB's payload_sender.py.

Usage:
  py send_payload.py payloads/helloworld.js
  py send_payload.py payloads/notification.js

ws_server.py doit etre en cours d'execution (port 50000).
La PS5 doit etre connectee.
"""

import socket
import sys
import os
import json

SERVER_IP   = "127.0.0.1"
SERVER_PORT = 50000

def send_payload(filepath):
    if not os.path.isfile(filepath):
        alt = os.path.join(os.path.dirname(__file__), filepath)
        filepath = alt if os.path.isfile(alt) else None

    if not filepath:
        print(f"  [!] Fichier introuvable: {sys.argv[1]}")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()

    print(f"  [+] {os.path.basename(filepath)} ({len(code)} octets)")

    body = json.dumps({"code": code}).encode("utf-8")
    request = (
        f"POST /inject HTTP/1.1\r\n"
        f"Host: {SERVER_IP}:{SERVER_PORT}\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((SERVER_IP, SERVER_PORT))
        sock.sendall(request)
    except Exception as e:
        print(f"  [!] Connexion impossible ({SERVER_IP}:{SERVER_PORT}): {e}")
        print(f"  [!] ws_server.py est-il en cours d'execution?")
        sys.exit(1)

    sock.settimeout(35)
    try:
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk: break
            data += chunk

        # Extraire le JSON depuis la reponse HTTP
        if b"\r\n\r\n" in data:
            body_resp = data.split(b"\r\n\r\n", 1)[1]
        else:
            body_resp = data

        result = json.loads(body_resp.decode("utf-8"))
        if result.get("status") == "ok":
            val = result.get("value", "")
            print(f"  [PS5 OK] {val if val and val != 'undefined' else '(pas de valeur de retour)'}")
        elif result.get("status") == "timeout":
            print("  [!] Timeout — pas de reponse de la PS5")
        else:
            print(f"  [PS5 ERR] {result.get('error', '?')}")
    except socket.timeout:
        print("  [!] Timeout (35s)")
    except Exception as e:
        print(f"  [!] Erreur: {e}")
    finally:
        sock.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: py send_payload.py <fichier.js>")
        print("       py send_payload.py payloads/helloworld.js")
        sys.exit(1)
    send_payload(sys.argv[1])

if __name__ == "__main__":
    main()
