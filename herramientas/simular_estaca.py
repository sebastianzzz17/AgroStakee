"""Simula una estaca ESP32-S3 enviando lecturas al servidor. Útil para la demo cuando no hay hardware.

Uso:
  python herramientas/simular_estaca.py --token est_xxx
  python herramientas/simular_estaca.py --token est_xxx --url http://127.0.0.1:5000 --historial 48 --cada 30

  --historial N   envía primero N lecturas "viejas" (una cada 30 minutos hacia atrás), como si la estaca
                  hubiera estado sin WiFi y las tuviera guardadas.
  --cada S        después sigue enviando una lectura cada S segundos (0 = no sigue).
  --seco          simula un suelo seco y ácido, para ver cómo cambian las alertas.

Solo usa la biblioteca estándar de Python. Los valores son inventados: no son mediciones reales."""
import argparse, json, math, random, sys, time, urllib.error, urllib.request

def lectura(minutos_atras, seco=False, rssi=None):
    hora = (time.localtime().tm_hour + time.localtime().tm_min / 60 - minutos_atras / 60) % 24
    sol = max(0.0, math.sin((hora - 6) / 12 * math.pi))          # 0 de noche, 1 al mediodía
    base_h = 14 if seco else 26
    l = {"ph": round(random.gauss(5.1 if seco else 6.2, 0.05), 2),
         "humedad_pct": round(max(3, base_h - 4 * sol + random.gauss(0, 0.4)), 1),
         "temp_suelo_c": round(26 + 7 * sol + random.gauss(0, 0.3), 1),
         "ce_us_cm": round(random.gauss(700 if seco else 450, 25)),
         "n_mg_kg": round(random.gauss(14 if seco else 32, 1.5)),
         "p_mg_kg": round(random.gauss(18, 1.5)),
         "k_mg_kg": round(random.gauss(150, 6)),
         "temp_aire_c": round(25 + 8 * sol + random.gauss(0, 0.4), 1),
         "humedad_aire_pct": round(85 - 30 * sol + random.gauss(0, 1.5), 1),
         "bateria_v": round(4.1 - minutos_atras / 60 / 24 * 0.02, 2),
         "edad_s": int(minutos_atras * 60)}
    if rssi is not None: l["rssi_dbm"] = rssi
    return l

def enviar(url, token, lecturas):
    req = urllib.request.Request(url.rstrip("/") + "/api/estaca/lecturas", data=json.dumps({"lecturas": lecturas}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:5000")
    ap.add_argument("--token", required=True, help="token de la estaca (Configuración > Mis estacas)")
    ap.add_argument("--historial", type=int, default=12)
    ap.add_argument("--cada", type=int, default=0)
    ap.add_argument("--seco", action="store_true")
    a = ap.parse_args()

    if a.historial:
        lote = [lectura(30 * i, a.seco) for i in range(min(a.historial, 100), 0, -1)]
        lote[-1]["rssi_dbm"] = -67
        cod, resp = enviar(a.url, a.token, lote)
        print(f"Historial: {cod} {resp}")
        if cod == 401: sys.exit("El servidor rechazó el token. Copia el que muestra la app al crear la estaca.")
    while a.cada > 0:
        cod, resp = enviar(a.url, a.token, [lectura(0, a.seco, rssi=random.randint(-80, -55))])
        print(time.strftime("%H:%M:%S"), cod, resp)
        time.sleep(a.cada)

if __name__ == "__main__":
    main()
