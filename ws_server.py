#!/usr/bin/env python3
"""
ws_server.py — Serveur Remote JS Loader pour PS5 FW 9.00

Port unique 50000:
  - PS5   → GET (WebSocket upgrade) → REPL interactif
  - send_payload.py → POST /inject  → injection directe

Usage:
  py ws_server.py
  py send_payload.py payloads/helloworld.js   (depuis un autre terminal)
"""

import socket
import threading
import queue
import base64
import hashlib
import struct
import json
import os

HOST     = "0.0.0.0"
PORT     = 50000
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# File d'injection partagee entre le thread REPL et les requetes POST
_inject_q = queue.Queue()
_ps5_conn = None   # connexion WebSocket PS5 active
_ps5_lock = threading.Lock()

# ─── WebSocket helpers ────────────────────────────────────────────────────────

def ws_accept_key(key):
    return base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()

def ws_handshake(conn, initial_data):
    """Terminer le handshake WebSocket a partir des donnees deja lues."""
    while b"\r\n\r\n" not in initial_data:
        chunk = conn.recv(4096)
        if not chunk:
            return False
        initial_data += chunk
    lines = initial_data.decode("utf-8", errors="replace").split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ": " in line:
            k, v = line.split(": ", 1)
            headers[k.lower()] = v
    key = headers.get("sec-websocket-key", "")
    if not key:
        return False
    resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {ws_accept_key(key)}\r\n\r\n"
    )
    conn.sendall(resp.encode())
    return True

def ws_recv(conn):
    def rx(n):
        buf = b""
        while len(buf) < n:
            c = conn.recv(n - len(buf))
            if not c:
                return None
            buf += c
        return buf
    h = rx(2)
    if not h:
        return None
    op = h[0] & 0x0f
    masked = (h[1] >> 7) & 1
    plen = h[1] & 0x7f
    if plen == 126:
        r = rx(2)
        if not r: return None
        plen = struct.unpack(">H", r)[0]
    elif plen == 127:
        r = rx(8)
        if not r: return None
        plen = struct.unpack(">Q", r)[0]
    mask = rx(4) if masked else b""
    if mask is None: return None
    payload = rx(plen)
    if payload is None: return None
    if masked:
        payload = bytes([b ^ mask[i % 4] for i, b in enumerate(payload)])
    return (op, payload)

def ws_send(conn, data, opcode=0x01):
    if isinstance(data, str):
        data = data.encode("utf-8")
    n = len(data)
    if n < 126:
        hdr = bytes([0x80 | opcode, n])
    elif n < 65536:
        hdr = bytes([0x80 | opcode, 126]) + struct.pack(">H", n)
    else:
        hdr = bytes([0x80 | opcode, 127]) + struct.pack(">Q", n)
    try:
        conn.sendall(hdr + data)
        return True
    except Exception:
        return False

# ─── Affichage PS5 ────────────────────────────────────────────────────────────

def print_ps5(payload_bytes, prefix=""):
    try:
        msg = json.loads(payload_bytes.decode("utf-8"))
        t = msg.get("type", "")
        if t == "result":
            tag = "OK " if msg.get("status") == "ok" else "ERR"
            val = msg.get("value") or msg.get("error") or ""
            print(f"\r  [PS5 {tag}] {val}")
        elif t == "log":
            print(f"\r  [PS5 LOG] {msg.get('msg', '')}")
        elif t == "pong":
            pass
        else:
            print(f"\r  [PS5] {payload_bytes.decode('utf-8', errors='replace')}")
    except Exception:
        print(f"\r  [PS5] {payload_bytes.decode('utf-8', errors='replace')}")

# ─── Envoyer a la PS5 (thread-safe) ──────────────────────────────────────────

def ps5_eval(code, timeout=30):
    result_q = queue.Queue()
    _inject_q.put({"code": code, "result_q": result_q})
    try:
        return result_q.get(timeout=timeout)
    except queue.Empty:
        return {"status": "timeout", "error": "Timeout 30s"}

# ─── Handler injection HTTP POST ──────────────────────────────────────────────

def handle_http_inject(conn, initial_data):
    """Traiter une requete POST /inject depuis send_payload.py."""
    try:
        # Lire le reste si necessaire
        data = initial_data
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk: break
            data += chunk

        header_part = data.split(b"\r\n\r\n", 1)
        headers_raw = header_part[0].decode("utf-8", errors="replace")
        body = header_part[1] if len(header_part) > 1 else b""

        # Content-Length
        content_length = 0
        for line in headers_raw.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())

        while len(body) < content_length:
            chunk = conn.recv(4096)
            if not chunk: break
            body += chunk

        msg = json.loads(body.decode("utf-8"))
        code = msg.get("code", "")

        if not code.strip():
            reply = {"status": "error", "error": "Pas de code"}
        elif _ps5_conn is None:
            reply = {"status": "error", "error": "Pas de PS5 connectee"}
        else:
            reply = ps5_eval(code, timeout=30)

        body_resp = json.dumps(reply).encode("utf-8")
        http_resp = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body_resp)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode() + body_resp
        conn.sendall(http_resp)
    except Exception as e:
        try:
            err = json.dumps({"status": "error", "error": str(e)}).encode()
            conn.sendall(b"HTTP/1.1 500 Error\r\nContent-Length: " + str(len(err)).encode() + b"\r\n\r\n" + err)
        except Exception:
            pass
    finally:
        conn.close()

# ─── Handler PS5 WebSocket ────────────────────────────────────────────────────

def handle_ps5(conn, addr, initial_data):
    global _ps5_conn

    if not ws_handshake(conn, initial_data):
        conn.close()
        return

    print(f"  [+] PS5 connectee depuis {addr[0]}:{addr[1]}")

    with _ps5_lock:
        _ps5_conn = conn

    # Message "ready" initial
    conn.settimeout(5)
    try:
        frame = ws_recv(conn)
        if frame and frame[0] == 0x01:
            info = json.loads(frame[1].decode("utf-8"))
            if info.get("type") == "ready":
                print(f"\n  === PS5 Remote JS Loader connecte ===")
                print(f"  FW        : {info.get('fw', '?')}")
                print(f"  kernelBase: {info.get('kernelBase', '?')}")
                print(f"  webkitBase: {info.get('webkitBase', '?')}")
                print(f"  =====================================\n")
    except Exception:
        pass
    finally:
        conn.settimeout(None)

    # Pas d'auto-load — le renderer a besoin de temps pour GC le carrier (~72MB).
    # L'utilisateur charge kernel.js manuellement une fois la session stable.
    print("  [*] Session prete. Commandes:")
    print("  [*]   send kernel.js         <- charger les primitives ROP/syscall")
    print("  [*]   send payloads/lapse.js <- kernel exploit")
    print("  [*]   <code JS>              <- executer du JS directement\n")


    def send_to_ps5(code, timeout=30):
        if not ws_send(conn, json.dumps({"type": "eval", "code": code})):
            return None
        conn.settimeout(timeout)
        try:
            return ws_recv(conn)
        except socket.timeout:
            return "timeout"
        finally:
            conn.settimeout(None)

    # Thread pour les injections send_payload.py
    def inject_worker():
        while True:
            try:
                item = _inject_q.get(timeout=1)
            except queue.Empty:
                try: conn.getpeername(); continue
                except Exception: break
            frame = send_to_ps5(item["code"])
            if frame and frame != "timeout" and frame[0] == 0x01:
                try:
                    item["result_q"].put(json.loads(frame[1].decode("utf-8")))
                    print_ps5(frame[1])
                    print("  > ", end="", flush=True)
                except Exception:
                    item["result_q"].put({"status": "ok", "value": "?"})
            elif frame == "timeout":
                item["result_q"].put({"status": "timeout"})
            else:
                item["result_q"].put({"status": "error", "error": "disconnected"})

    threading.Thread(target=inject_worker, daemon=True).start()

    # REPL
    while True:
        # Messages PS5 non-sollicites
        conn.setblocking(False)
        try:
            if conn.recv(1, socket.MSG_PEEK) == b"":
                print("\n  [!] PS5 deconnectee"); break
            conn.setblocking(True)
            frame = ws_recv(conn)
            if not frame: print("\n  [!] PS5 deconnectee"); break
            if frame[0] == 0x08: print("\n  [!] PS5 deconnectee"); break
            if frame[0] == 0x01: print_ps5(frame[1])
        except BlockingIOError:
            pass
        conn.setblocking(True)

        try:
            print("  > ", end="", flush=True)
            first = input().strip()

            if first.lower() == "exit":
                ws_send(conn, json.dumps({"type": "close"}), opcode=0x08)
                conn.close(); return

            if first.lower() == "help":
                print("  send <fichier.js>  — Envoyer un fichier JS")
                print("  fire               — Notif PS5 + crash renderer (commitRce)")
                print("  <code JS>          — Executer (ligne vide pour valider)")
                print("  exit               — Quitter")
                print("  Ou: py send_payload.py <fichier.js>  (autre terminal)")
                continue

            if first.lower() in ("fire", "commit"):
                ws_send(conn, json.dumps({"type": "fire"}))
                conn.settimeout(5)
                try:
                    f = ws_recv(conn)
                    if f and f[0] == 0x01: print_ps5(f[1])
                except socket.timeout:
                    print("  [OK] commitRce declenche (renderer a certainement crashe)")
                finally:
                    conn.settimeout(None)
                continue

            if first.lower().startswith("send "):
                fname = first[5:].strip()
                for p in [fname, os.path.join(os.path.dirname(__file__), fname)]:
                    if os.path.isfile(p):
                        with open(p, encoding="utf-8") as f:
                            code = f.read()
                        print(f"  [*] Envoi '{p}' ({len(code)} octets)...")
                        frame = send_to_ps5(code)
                        if frame == "timeout": print("  [!] Timeout")
                        elif frame and frame[0] == 0x01: print_ps5(frame[1])
                        elif not frame: print("  [!] PS5 deconnectee"); break
                        break
                else:
                    print(f"  [!] Fichier introuvable: {fname}")
                continue

            # Code JS multi-ligne
            lines = [first] if first else []
            while True:
                line = input()
                if line.strip() == "": break
                lines.append(line)
            code = "\n".join(lines)
            if not code.strip(): continue

            frame = send_to_ps5(code)
            if frame == "timeout": print("  [!] Timeout (30s)")
            elif frame and frame[0] == 0x01: print_ps5(frame[1])
            elif not frame: print("  [!] PS5 deconnectee"); break

        except (EOFError, KeyboardInterrupt):
            print("\n  [!] Interruption"); break

    with _ps5_lock:
        _ps5_conn = None
    conn.close()
    print("  [*] Session terminee. En attente PS5...\n")

# ─── Dispatcher (detection WS vs HTTP) ───────────────────────────────────────

def dispatch(conn, addr):
    """Detecter si c'est la PS5 (WebSocket GET) ou send_payload.py (POST HTTP)."""
    conn.settimeout(10)
    try:
        initial = conn.recv(8)
        if not initial:
            conn.close(); return
    except Exception:
        conn.close(); return
    finally:
        conn.settimeout(None)

    if initial[:4] == b"POST":
        handle_http_inject(conn, initial)
    elif initial[:3] == b"GET":
        handle_ps5(conn, addr, initial)
    else:
        conn.close()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n  === PS5 Remote JS Loader Server ===")
    print(f"  Port {PORT} : PS5 WebSocket + send_payload.py")
    print(f"  Usage     : py send_payload.py payloads/helloworld.js\n")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=dispatch, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\n  [!] Arret")
    finally:
        srv.close()

if __name__ == "__main__":
    main()
