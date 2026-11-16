#!/usr/bin/env python3
"""
Speicher-Übersicht – eigene Web-App für Marstek-Venus-Speicher.

Läuft auf einem Rechner im Heimnetz (Windows, Mac, Linux, Raspberry Pi),
spricht die Speicher über deren lokale Schnittstelle ("Open API", UDP) an
und stellt eine Web-Oberfläche bereit, die am Handy im Browser geöffnet wird.

Die Oberfläche liegt in index.html im selben Ordner.

Start:        python speicher_app.py
Vorschau:     python speicher_app.py --demo      (ohne echte Geräte)
Mit PIN:      python speicher_app.py --pin 1234

Benötigt nur Python 3.8 oder neuer, keine Zusatzpakete.
"""
import argparse
import hmac
import ipaddress
import json
import os
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "speicher_config.json")
DB_FILE = os.path.join(HERE, "speicher_verlauf.db")
API_PORT = 30000          # Standard-Port der Marstek Open API
OFFLINE_AFTER = 3         # so viele erfolglose Abfragen in Folge = offline
MODES = ("Auto", "AI", "Manual", "Passive")


# --------------------------------------------------------------- UDP-Client
class MarstekUdp:
    """JSON über UDP. Ein Socket, Abfragen strikt nacheinander."""

    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            # Manche Firmware antwortet nur an denselben Port, daher lokal
            # ebenfalls den API-Port verwenden, wenn er frei ist.
            self.sock.bind(("", API_PORT))
        except OSError:
            self.sock.bind(("", 0))
        self.local_port = self.sock.getsockname()[1]

    def _next_id(self):
        self.seq = self.seq % 60000 + 1
        return self.seq

    def request(self, ip, port, method, params, timeout=2.5, tries=2):
        """Gibt das 'result' zurück oder None, wenn keine Antwort kommt."""
        with self.lock:
            for _ in range(tries):
                rid = self._next_id()
                msg = json.dumps({"id": rid, "method": method, "params": params})
                try:
                    self.sock.sendto(msg.encode(), (ip, port))
                except OSError:
                    return None
                end = time.time() + timeout
                while True:
                    left = end - time.time()
                    if left <= 0:
                        break
                    self.sock.settimeout(left)
                    try:
                        data, addr = self.sock.recvfrom(8192)
                    except socket.timeout:
                        break
                    except OSError:
                        continue      # z. B. "Port nicht erreichbar" unter Windows
                    try:
                        obj = json.loads(data.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if not isinstance(obj, dict) or "method" in obj:
                        continue
                    if obj.get("id") == rid and addr[0] == ip:
                        res = obj.get("result")
                        return res if isinstance(res, dict) else None
        return None

    def discover(self, port=API_PORT, wait=3.0):
        """Rundruf ins Heimnetz; liefert gefundene Geräte."""
        found = {}
        with self.lock:
            rid = self._next_id()
            msg = json.dumps({"id": rid, "method": "Marstek.GetDevice",
                              "params": {"ble_mac": "0"}}).encode()
            for target in ("255.255.255.255", "<broadcast>"):
                try:
                    self.sock.sendto(msg, (target, port))
                except OSError:
                    pass
            end = time.time() + wait
            while True:
                left = end - time.time()
                if left <= 0:
                    break
                self.sock.settimeout(left)
                try:
                    data, addr = self.sock.recvfrom(8192)
                except socket.timeout:
                    break
                except OSError:
                    continue
                try:
                    obj = json.loads(data.decode("utf-8", "replace"))
                except ValueError:
                    continue
                res = obj.get("result") if isinstance(obj, dict) else None
                if isinstance(res, dict) and "device" in res:
                    found[addr[0]] = {"ip": addr[0], "port": port,
                                      "device": str(res.get("device", "")),
                                      "ver": res.get("ver")}
        return list(found.values())


# ------------------------------------------------------------------- Zustand
class App:
    def __init__(self, demo=False, pin=None):
        self.demo = demo
        self.pin = pin
        self.udp = MarstekUdp()
        self.cfg_lock = threading.Lock()
        self.cfg = {"devices": [], "interval": 60, "invert": False, "ct_invert": False}
        self.state = {}                      # Schlüssel "ip:port"
        self.wake = threading.Event()
        self.db_lock = threading.Lock()
        self.db = sqlite3.connect(":memory:" if demo else DB_FILE,
                                  check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS samples("
                        "ts INTEGER, dev TEXT, soc REAL, power REAL,"
                        "e_in REAL, e_out REAL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS i_s ON samples(dev, ts)")
        self.db.commit()
        if not demo:
            self.load_cfg()

    # --- Konfiguration
    def load_cfg(self):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.cfg.update({k: data[k] for k in self.cfg if k in data})
        except (OSError, ValueError):
            pass

    def save_cfg(self):
        if self.demo:
            return
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_FILE)

    @staticmethod
    def key(d):
        return "%s:%s" % (d["ip"], d["port"])

    def find(self, key):
        with self.cfg_lock:
            for d in self.cfg["devices"]:
                if self.key(d) == key:
                    return dict(d)
        return None

    # --- Abfrage
    def poll_device(self, d, cycle):
        k = self.key(d)
        st = self.state.setdefault(k, {"fails": 0, "online": None, "last_seen": 0})
        ip, port = d["ip"], int(d["port"])
        es = self.udp.request(ip, port, "ES.GetStatus", {"id": 0})
        if es is None:
            st["fails"] += 1
            if st["fails"] >= OFFLINE_AFTER or st["online"] is None:
                st["online"] = False
            return
        st.update(fails=0, online=True, last_seen=int(time.time()), es=es)
        for field, method in (("mode", "ES.GetMode"), ("em", "EM.GetStatus"),
                              ("bat", "Bat.GetStatus")):
            time.sleep(0.3)
            res = self.udp.request(ip, port, method, {"id": 0})
            if res is not None:
                st[field] = res
        if cycle % 10 == 0 or "wifi" not in st:
            time.sleep(0.3)
            res = self.udp.request(ip, port, "Wifi.GetStatus", {"id": 0})
            if res is not None:
                st["wifi"] = res
        if "info" not in st:
            time.sleep(0.3)
            res = self.udp.request(ip, port, "Marstek.GetDevice", {"ble_mac": "0"})
            if res is not None:
                st["info"] = res
        soc = num(es.get("bat_soc"))
        if soc is None:
            soc = num(st.get("bat", {}).get("soc"))
        with self.db_lock:
            self.db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?)",
                            (int(time.time()), k, soc, self.power_of(st),
                             num(es.get("total_grid_input_energy")),
                             num(es.get("total_grid_output_energy"))))
            self.db.commit()

    def power_of(self, st):
        """Leistung am Netzanschluss des Speichers. Positiv = Entladen."""
        p = num(st.get("es", {}).get("ongrid_power"))
        if p is None:
            p = num(st.get("mode", {}).get("ongrid_power"))
        if p is not None and self.cfg.get("invert"):
            p = -p
        return p

    def poll_loop(self):
        cycle = 0
        while True:
            with self.cfg_lock:
                devs = [dict(d) for d in self.cfg["devices"]]
                interval = max(15, int(self.cfg.get("interval", 60)))
            for d in devs:
                try:
                    self.poll_device(d, cycle)
                except Exception as e:           # eine Störung darf den Lauf nicht beenden
                    print("Abfrage %s fehlgeschlagen: %s" % (d.get("ip"), e))
                time.sleep(0.5)
            cycle += 1
            if cycle % 500 == 0:
                with self.db_lock:
                    self.db.execute("DELETE FROM samples WHERE ts < ?",
                                    (int(time.time()) - 30 * 86400,))
                    self.db.commit()
            self.wake.wait(interval)
            self.wake.clear()

    # --- Ausgabe für die Oberfläche
    def today(self, k):
        lt = time.localtime()
        midnight = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))
        with self.db_lock:
            first = self.db.execute(
                "SELECT e_in, e_out FROM samples WHERE dev=? AND ts>=? AND e_in IS NOT NULL "
                "ORDER BY ts LIMIT 1", (k, midnight)).fetchone()
            last = self.db.execute(
                "SELECT e_in, e_out FROM samples WHERE dev=? AND ts>=? AND e_in IS NOT NULL "
                "ORDER BY ts DESC LIMIT 1", (k, midnight)).fetchone()
        if not first or not last:
            return None, None
        d_in = last[0] - first[0] if None not in (last[0], first[0]) else None
        d_out = last[1] - first[1] if None not in (last[1], first[1]) else None
        return (d_in if d_in is None or d_in >= 0 else None,
                d_out if d_out is None or d_out >= 0 else None)

    def snapshot(self):
        with self.cfg_lock:
            devs = [dict(d) for d in self.cfg["devices"]]
            interval, invert = self.cfg["interval"], self.cfg["invert"]
            ct_inv = -1.0 if self.cfg.get("ct_invert") else 1.0
        out = []
        for d in devs:
            k = self.key(d)
            st = self.state.get(k, {})
            es, mode, em = st.get("es", {}), st.get("mode", {}), st.get("em", {})
            bat, wifi, info = st.get("bat", {}), st.get("wifi", {}), st.get("info", {})
            soc = num(es.get("bat_soc"))
            if soc is None:
                soc = num(bat.get("soc"))
            ct = em.get("ct_state")
            if ct is None:
                ct = mode.get("ct_state")
            e_in, e_out = self.today(k)
            phases = [num(em.get(x)) for x in ("a_power", "b_power", "c_power")]
            phases = [p * ct_inv if p is not None else None for p in phases]
            grid = num(em.get("total_power"))
            grid = grid * ct_inv if grid is not None else None
            out.append({
                "key": k, "name": d["name"], "ip": d["ip"], "port": d["port"],
                "phase": d.get("phase", ""),
                "online": st.get("online"), "last_seen": st.get("last_seen", 0),
                "soc": soc,
                "cap_wh": num(es.get("bat_cap")) or num(bat.get("rated_capacity")),
                "rest_wh": num(bat.get("bat_capacity")),
                "power": self.power_of(st),
                "offgrid": num(es.get("offgrid_power")),
                "mode": mode.get("mode") if isinstance(mode.get("mode"), str) else None,
                "ct": ct,
                "phases": phases,
                "grid_total": grid,
                "temp": num(bat.get("bat_temp")),
                "rssi": num(wifi.get("rssi")), "ssid": wifi.get("ssid"),
                "model": info.get("device"), "fw": info.get("ver"),
                "today_in_wh": e_in, "today_out_wh": e_out,
            })
        return {"now": int(time.time()), "demo": self.demo, "interval": interval,
                "invert": invert, "ct_invert": ct_inv < 0, "devices": out}

    def history(self, hours):
        since = int(time.time()) - hours * 3600
        with self.db_lock:
            rows = self.db.execute("SELECT dev, ts, soc, power FROM samples "
                                   "WHERE ts>=? ORDER BY ts", (since,)).fetchall()
        res = {}
        for dev, ts, soc, power in rows:
            res.setdefault(dev, []).append([ts, soc, power])
        for dev, lst in res.items():            # ausdünnen auf höchstens ~300 Punkte
            step = max(1, len(lst) // 300)
            res[dev] = lst[::step]
        return {"since": since, "series": res}

    # --- Aktionen
    def add_device(self, name, ip, port, phase=""):
        try:
            ip = str(ipaddress.ip_address(str(ip).strip()))
        except ValueError:
            raise ValueError("IP-Adresse ungültig")
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError("Port ungültig")
        name = (str(name).strip() or ip)[:40]
        phase = phase if phase in ("L1", "L2", "L3") else ""
        with self.cfg_lock:
            for d in self.cfg["devices"]:
                if d["ip"] == ip and int(d["port"]) == port:
                    d["name"], d["phase"] = name, phase
                    break
            else:
                self.cfg["devices"].append({"name": name, "ip": ip, "port": port, "phase": phase})
            self.save_cfg()
        self.wake.set()

    def remove_device(self, key):
        with self.cfg_lock:
            self.cfg["devices"] = [d for d in self.cfg["devices"] if self.key(d) != key]
            self.save_cfg()
        self.state.pop(key, None)

    def set_mode(self, key, body):
        d = self.find(key)
        if not d:
            raise ValueError("Gerät unbekannt")
        mode = body.get("mode")
        if mode not in MODES:
            raise ValueError("Modus unbekannt")
        if mode == "Auto":
            cfg = {"mode": "Auto", "auto_cfg": {"enable": 1}}
        elif mode == "AI":
            cfg = {"mode": "AI", "ai_cfg": {"enable": 1}}
        else:
            power = int(body.get("power", 0))
            if not 0 <= power <= 2500:
                raise ValueError("Leistung muss zwischen 0 und 2500 W liegen")
            # Annahme: positiv = Entladen, negativ = Laden (umkehrbar in den Einstellungen)
            signed = power if body.get("richtung") == "entladen" else -power
            if self.cfg.get("invert"):
                signed = -signed
            if mode == "Passive":
                minutes = int(body.get("dauer_min", 60))
                if not 1 <= minutes <= 1440:
                    raise ValueError("Dauer muss zwischen 1 und 1440 Minuten liegen")
                cfg = {"mode": "Passive",
                       "passive_cfg": {"power": signed, "cd_time": minutes * 60}}
            else:
                start, ende = str(body.get("start", "")), str(body.get("ende", ""))
                for t in (start, ende):
                    time.strptime(t, "%H:%M")
                cfg = {"mode": "Manual",
                       "manual_cfg": {"time_num": 0, "start_time": start, "end_time": ende,
                                      "week_set": 127, "power": signed, "enable": 1}}
        res = self.udp.request(d["ip"], int(d["port"]), "ES.SetMode",
                               {"id": 0, "config": cfg}, timeout=4, tries=2)
        self.wake.set()
        if res is None:
            raise RuntimeError("Keine Antwort vom Speicher")
        if res.get("set_result") is not True:
            raise RuntimeError("Speicher hat die Einstellung abgelehnt")


def num(v):
    try:
        return float(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------- Demo-Geräte
def start_demo(app):
    """Drei simulierte Speicher auf dem eigenen Rechner; der dritte antwortet nicht."""
    sims = [{"port": 30001, "soc": 15.0, "p": -231, "mode": "Auto", "ct": 1, "e_in": 41200, "e_out": 38800},
            {"port": 30002, "soc": 11.0, "p": 0, "mode": "Auto", "ct": 0, "e_in": 39700, "e_out": 37100}]

    def serve(s):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", s["port"]))
        last = time.time()
        while True:
            data, addr = sock.recvfrom(8192)
            try:
                req = json.loads(data)
            except ValueError:
                continue
            now = time.time()
            wh = -s["p"] * (now - last) / 3600.0 * 200     # Zeitraffer für die Vorschau
            last = now
            s["soc"] = min(100.0, max(5.0, s["soc"] + wh / 51.2))
            if wh > 0:
                s["e_in"] += wh
            else:
                s["e_out"] -= wh
            m = req.get("method")
            if m == "ES.GetStatus":
                r = {"id": 0, "bat_soc": round(s["soc"]), "bat_cap": 5120, "pv_power": 0,
                     "ongrid_power": s["p"], "offgrid_power": 0,
                     "total_grid_output_energy": round(s["e_out"]),
                     "total_grid_input_energy": round(s["e_in"]), "total_load_energy": 0}
            elif m == "ES.GetMode":
                r = {"id": 0, "mode": s["mode"], "ongrid_power": s["p"], "offgrid_power": 0,
                     "bat_soc": round(s["soc"]), "ct_state": s["ct"]}
            elif m == "EM.GetStatus":
                r = {"id": 0, "ct_state": s["ct"], "a_power": -410 if s["ct"] else 0,
                     "b_power": 120 if s["ct"] else 0, "c_power": 85 if s["ct"] else 0,
                     "total_power": -205 if s["ct"] else 0}
            elif m == "Bat.GetStatus":
                r = {"id": 0, "soc": round(s["soc"]), "charg_flag": True, "dischrg_flag": True,
                     "bat_temp": 21.0, "bat_capacity": round(51.2 * s["soc"]),
                     "rated_capacity": 5120.0}
            elif m == "Wifi.GetStatus":
                r = {"id": 0, "ssid": "Heimnetz", "rssi": -61, "sta_ip": "127.0.0.1"}
            elif m == "Marstek.GetDevice":
                r = {"device": "VenusE 3.0", "ver": 148, "ip": "127.0.0.1"}
            elif m == "ES.SetMode":
                c = req.get("params", {}).get("config", {})
                s["mode"] = c.get("mode", s["mode"])
                sub = c.get("passive_cfg") or c.get("manual_cfg")
                s["p"] = sub["power"] if sub else (-231 if s["ct"] else 0)
                r = {"id": 0, "set_result": True}
            else:
                continue
            sock.sendto(json.dumps({"id": req.get("id"), "src": "Demo", "result": r}).encode(), addr)

    for s in sims:
        threading.Thread(target=serve, args=(s,), daemon=True).start()
    app.cfg["devices"] = [{"name": "Venus E L1", "ip": "127.0.0.1", "port": 30001, "phase": "L1"},
                          {"name": "Venus E L2", "ip": "127.0.0.1", "port": 30002, "phase": "L2"},
                          {"name": "Venus E L3", "ip": "127.0.0.1", "port": 30003, "phase": "L3"}]
    app.cfg["interval"] = 15


# ---------------------------------------------------------------- Webserver
def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Speicher/2.0"

        def log_message(self, *a):
            pass

        def send_json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            if not app.pin:
                return True
            return hmac.compare_digest(self.headers.get("X-Pin", "").encode(),
                                       app.pin.encode())

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in STATIC_FILES:
                rel, ctype = STATIC_FILES[path]
                try:
                    with open(os.path.join(HERE, rel), "rb") as f:
                        body = f.read()
                except OSError:
                    return self.send_json({"error": rel + " fehlt"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(body)
                return
            if not path.startswith("/api/"):
                return self.send_json({"error": "Nicht gefunden"}, 404)
            if not self.allowed():
                return self.send_json({"error": "PIN erforderlich"}, 401)
            if path == "/api/state":
                return self.send_json(app.snapshot())
            if path == "/api/history":
                return self.send_json(app.history(24))
            self.send_json({"error": "Nicht gefunden"}, 404)

        def do_POST(self):
            if not self.allowed():
                return self.send_json({"error": "PIN erforderlich"}, 401)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("Ungültige Anfrage")
                p = self.path
                if p == "/api/devices":
                    app.add_device(body.get("name", ""), body.get("ip", ""),
                                   body.get("port", API_PORT), body.get("phase", ""))
                elif p == "/api/devices/delete":
                    app.remove_device(str(body.get("key", "")))
                elif p == "/api/discover":
                    return self.send_json({"found": app.udp.discover()})
                elif p == "/api/mode":
                    app.set_mode(str(body.get("key", "")), body)
                elif p == "/api/settings":
                    with app.cfg_lock:
                        if "interval" in body:
                            app.cfg["interval"] = min(3600, max(15, int(body["interval"])))
                        if "invert" in body:
                            app.cfg["invert"] = bool(body["invert"])
                        if "ct_invert" in body:
                            app.cfg["ct_invert"] = bool(body["ct_invert"])
                        app.save_cfg()
                    app.wake.set()
                elif p == "/api/refresh":
                    app.wake.set()
                else:
                    return self.send_json({"error": "Nicht gefunden"}, 404)
                self.send_json({"ok": True})
            except (ValueError, KeyError, TypeError) as e:
                self.send_json({"error": str(e) or "Eingabe ungültig"}, 400)
            except RuntimeError as e:
                self.send_json({"error": str(e)}, 502)
    return Handler


STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icons/icon-180.png": ("icons/icon-180.png", "image/png"),
    "/icons/icon-192.png": ("icons/icon-192.png", "image/png"),
    "/icons/icon-512.png": ("icons/icon-512.png", "image/png"),
}


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()




def main():
    ap = argparse.ArgumentParser(description="Speicher-Übersicht für Marstek Venus")
    ap.add_argument("--port", type=int, default=8080, help="Port der Web-Oberfläche")
    ap.add_argument("--pin", help="PIN, die im Browser abgefragt wird")
    ap.add_argument("--demo", action="store_true", help="Vorschau mit simulierten Geräten")
    args = ap.parse_args()

    app = App(demo=args.demo, pin=args.pin)
    if args.demo:
        start_demo(app)
    threading.Thread(target=app.poll_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(app))
    print("Speicher-Übersicht läuft.")
    print("  Am Handy im selben WLAN öffnen:  http://%s:%d" % (lan_ip(), args.port))
    print("  Auf diesem Rechner:              http://localhost:%d" % args.port)
    print("  UDP-Port für die Speicher:       %d" % app.udp.local_port)
    print("Beenden mit Strg+C.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()
