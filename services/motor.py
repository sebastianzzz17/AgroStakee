"""Motor de reglas transparente (sin ML), en español e inglés.
Clima (NASA): lluvia, temperatura media, máxima y mínima, estrés térmico, heladas, evaporación (Hargreaves-Samani,
FAO-56), humedad del suelo, lluvias extremas, verdor (NDVI), veranillo, pendiente y tendencias de largo plazo.
Suelo: pH, N-P-K, humedad, temperatura, salinidad y textura (a mano o desde la estaca).
Cultivos: ciclo, agua, pH, familia, fijación de nitrógeno, cobertura, forraje, materia orgánica y mercado.
Prioridades del agricultor: agua, forraje, nitrógeno, erosión, materia orgánica y mercado.

Idioma: app.py fija IDIOMA ("es" o "en") en cada petición; tr(es, en) elige el texto."""
import calendar, contextvars, json, math, random, re
from datetime import date
from itertools import product
import db

IDIOMA = contextvars.ContextVar("idioma", default="es")
def _en(): return IDIOMA.get() == "en"
def tr(es, en): return en if _en() else es
def _num(x, d=1):
    s = f"{round(x, d):g}" if d else str(round(x))
    return s if _en() else s.replace(".", ",")

MESES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
MESES_EN = ["January","February","March","April","May","June","July","August","September","October","November","December"]
MC = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
MC_EN = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
TEMPORADAS = [("Primeras lluvias", "First rains", 0), ("Segundas lluvias", "Second rains", 4), ("Verano", "Dry season", 8)]
PRIORIDADES = ("agua", "forraje", "nitrogeno", "erosion", "materia_organica", "mercado")
ALIAS = {"suelo": "nitrogeno", "ingreso": "mercado"}
IND_KEYS = ("agua", "nitrogeno", "erosion", "materia_organica", "forraje", "mercado", "resiliencia")
NOM_IND = {"agua": ("Uso del agua", "Water use"), "nitrogeno": ("Nitrógeno", "Nitrogen"), "erosion": ("Frena la erosión", "Erosion control"),
           "materia_organica": ("Materia orgánica", "Organic matter"), "forraje": ("Forraje", "Forage"), "mercado": ("Mercado", "Market"),
           "resiliencia": ("Aguante en años secos", "Dry-year resilience")}
NIVEL = {"bajo": .2, "medio": .5, "alto": .8}
RETENCION = {"arenoso": .85, "franco": 1.0, "arcilloso": 1.1}
LARGO = 135
LEGUM = ("leguminosa", "abono_verde")
NO_RIEGO = ("cobertura", "abono_verde")   # coberturas y abonos verdes viven de la lluvia: no se riegan ni suman agua de riego

def _productivo(c): return c is not None and c["tipo"] not in NO_RIEGO

def _meta_n(c):
    """Nivel de nitrógeno (0 a 1) hacia el que lleva el suelo repetir este cultivo: las leguminosas lo suben,
    los cultivos exigentes lo bajan. Aproximación cualitativa, no un balance de nutrientes."""
    if c["fija_n"]: return .85
    if c["tipo"] == "cobertura": return .5
    return .55 - .4 * c["demanda_n"]
UMBRAL_CALOR = 35   # °C: día de calor si la máxima pasa de este valor
UMBRAL_FRIO = 18    # °C: día frío si la mínima baja de este valor (para cultivos de tierra caliente; ajustable)
DIAS_MES = [calendar.monthrange(2023, m + 1)[1] for m in range(12)]
ET0_REF = 5.0       # mm/día, evaporación típica de tierras bajas tropicales: referencia para ajustar el agua de cada cultivo

def _clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def _nivel(x): return "bajo" if x < .35 else "medio" if x < .65 else "alto"
def _nivel_eros(x): return "bajo" if x < .15 else "medio" if x < .35 else "alto"
def _niv3(v, a, b): return "bajo" if v < a else "medio" if v < b else "alto"
def _nt(n): return tr(n, {"bajo": "low", "medio": "medium", "alto": "high"}.get(n, n))
def _sem(x): return "verde" if x >= 70 else "amarillo" if x >= 45 else "rojo"
def _mes(n): return (MESES_EN if _en() else MESES)[n % 12]
def _nom(c): return c["nombre_en"] if _en() and c.get("nombre_en") else c["nombre"]
def _temp(i): return TEMPORADAS[i][1] if _en() else TEMPORADAS[i][0]

# ---------------------------------------------------------------- Evaporación (FAO-56)
def _ra(lat, mes):
    """Radiación extraterrestre a mitad de mes (FAO-56, ec. 21), en mm/día equivalentes (x 0,408)."""
    j = round(30.42 * mes - 15.2)
    phi = math.radians(lat)
    dr = 1 + .033 * math.cos(2 * math.pi * j / 365)
    d = .409 * math.sin(2 * math.pi * j / 365 - 1.39)
    ws = math.acos(_clamp(-math.tan(phi) * math.tan(d), -1, 1))
    ra = 24 * 60 / math.pi * .082 * dr * (ws * math.sin(phi) * math.sin(d) + math.cos(phi) * math.cos(d) * math.sin(ws))
    return .408 * ra

def et0(tmed, tmax, tmin, lat, mes):
    """Evapotranspiración de referencia, Hargreaves-Samani (FAO-56, ec. 52), en mm/día."""
    return .0023 * (tmed + 17.8) * math.sqrt(max(0.0, tmax - tmin)) * _ra(lat, mes)

def _completar(cl, lat):
    """Agrega los campos derivados que falten (series mensuales de temperatura, evaporación y días)."""
    cl = dict(cl)
    onda = [math.cos(2 * math.pi * (m - 3) / 12) for m in range(12)]
    if "temp_mensual" not in cl:
        cl["temp_mensual"] = [round(cl["temp_media"] + 1.3 * o, 1) for o in onda]
        cl["tmax_mensual"] = [round(cl.get("tmax_media", cl["temp_media"] + 5.5) + 1.5 * o, 1) for o in onda]
        cl["tmin_mensual"] = [round(cl.get("tmin_media", cl["temp_media"] - 5) + .8 * o, 1) for o in onda]
    if "evap_mensual_mm" not in cl:
        cl["evap_mensual_mm"] = [round(et0(cl["temp_mensual"][m], cl["tmax_mensual"][m], cl["tmin_mensual"][m], lat, m + 1) * DIAS_MES[m]) for m in range(12)]
    if "dias_lluvia_mensual" not in cl:   # DE EJEMPLO: unos 11 mm por día de lluvia
        cl["dias_lluvia_mensual"] = [round(min(.75 * DIAS_MES[m], cl["lluvia_mensual_mm"][m] / 11)) for m in range(12)]
    if "dias_calor_mensual" not in cl:    # DE EJEMPLO: reparte los días de calor del año según qué tan caliente es cada mes
        tmx = sum(cl["tmax_mensual"]) / 12
        w = [math.exp(cl["tmax_mensual"][m] - tmx) for m in range(12)]
        cl["dias_calor_mensual"] = [min(DIAS_MES[m], round(cl.get("dias_estres_termico", 0) * w[m] / sum(w))) for m in range(12)]
    if "dias_frio_mensual" not in cl:     # DE EJEMPLO: mínima diaria con variación normal de 1,2 °C alrededor del promedio del mes
        cl["dias_frio_mensual"] = [round(DIAS_MES[m] * .5 * (1 + math.erf((UMBRAL_FRIO - cl["tmin_mensual"][m]) / (1.2 * math.sqrt(2))))) for m in range(12)]
    cl.setdefault("tmax_media", round(sum(cl["tmax_mensual"]) / 12, 1))
    cl.setdefault("tmin_media", round(sum(cl["tmin_mensual"]) / 12, 1))
    cl.setdefault("tmin_absoluta", round(min(cl["tmin_mensual"]) - 3, 1))
    cl.setdefault("dias_helada", 0)
    cl.setdefault("dias_lluvia_extrema", 0)
    cl.setdefault("lluvia_max_dia_mm", round(max(cl["lluvia_mensual_mm"]) / 3))
    cl["evap_anual_mm"] = round(sum(cl["evap_mensual_mm"]))
    cl["lluvia_anual_mm"] = round(sum(cl["lluvia_mensual_mm"]))
    cl["f_evap"] = round(_clamp(cl["evap_anual_mm"] / 365 / ET0_REF, .85, 1.25), 2)
    return cl

# ---------------------------------------------------------------- Zonas guardadas y puntos libres del mapa
_PUNTO = re.compile(r"^p:(-?\d{1,2}(?:\.\d{1,6})?),(-?\d{1,3}(?:\.\d{1,6})?)$")

def es_punto(zid): return bool(_PUNTO.match(str(zid or "")))

def punto_coords(zid):
    m = _PUNTO.match(str(zid or ""))
    if not m: raise ValueError("punto no válido")
    lat, lon = float(m[1]), float(m[2])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180): raise ValueError("punto fuera de rango")
    return round(lat, 3), round(lon, 3)

def id_punto(lat, lon): return f"p:{round(float(lat), 3)},{round(float(lon), 3)}"

def km(a, b, c, d):
    r = math.pi / 180
    x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))

def zona_cercana(lat, lon):
    zs = db.consultar("SELECT * FROM zonas")
    z = min(zs, key=lambda z: km(lat, lon, float(z["lat"]), float(z["lon"])))
    return z, round(km(lat, lon, float(z["lat"]), float(z["lon"])))

def canon(zona_id):
    """Forma única del id de un punto ("p:9.810,-75.123" y "p:9.81,-75.123" son el mismo)."""
    return id_punto(*punto_coords(zona_id)) if es_punto(zona_id) else zona_id

def zona(zona_id):
    """Fila de la zona. Un punto libre ("p:lat,lon") hereda textura y riego típicos de la zona guardada más cercana."""
    if es_punto(zona_id):
        zona_id = canon(zona_id)
        lat, lon = punto_coords(zona_id)
        zc, d = zona_cercana(lat, lon)
        nom = zc["nombre"].split(" (")[0]
        return {"id": zona_id, "nombre": tr(f"Mi punto ({_num(lat, 3)}, {_num(lon, 3)})", f"My point ({lat}, {lon})"), "lat": lat, "lon": lon,
                "suelo": zc["suelo"], "riego": zc["riego"], "punto": True, "cercana": zc["id"], "cercana_nombre": nom, "km_cercana": d}
    f = db.consultar("SELECT * FROM zonas WHERE id=?", (zona_id,))
    if not f: raise KeyError(zona_id)
    return f[0]

def clima_de(zona_id):
    """Clima de la zona. Para un punto libre: el descargado de NASA para ese punto; si todavía no se ha podido
    descargar, el de la zona guardada más cercana (y se marca como no verificado)."""
    zona_id = canon(zona_id)
    f = db.consultar("SELECT datos, verificado FROM clima WHERE zona_id=?", (zona_id,))
    if es_punto(zona_id):
        lat, _ = punto_coords(zona_id)
        if f: return _completar(json.loads(f[0]["datos"]), lat), bool(f[0]["verificado"])
        z = zona(zona_id)
        cl, _ = clima_de(z["cercana"])
        return dict(cl, prestado_de=z["cercana"]), False
    if not f: return None, False
    z = db.consultar("SELECT lat FROM zonas WHERE id=?", (zona_id,))
    return _completar(json.loads(f[0]["datos"]), float(z[0]["lat"]) if z else 10.0), bool(f[0]["verificado"])

def _reales(zona_id):
    """Datos recientes descargados de NASA POWER y MODIS para la zona (solo lo guardado, sin usar internet)."""
    try:
        from services import descargas
        z = zona(zona_id)
        return descargas.recientes(float(z["lat"]), float(z["lon"]), solo_cache=True)
    except Exception:
        return None

def _lluvia(cl, offset, meses=4):
    m0 = cl["inicio_lluvias_mes"] - 1 + offset
    return sum(cl["lluvia_mensual_mm"][(m0 + i) % 12] for i in range(meses))

def _dem(c, ctx):
    """Agua que pide el cultivo, ajustada por la evaporación de la zona."""
    return c["agua_mm"] * ctx.get("f_evap", 1.0)

def _ratio(c, lluvia, ctx, piso=.85):
    if c["agua_mm"] <= 0: return 1.0
    r = min(1.0, lluvia * RETENCION[ctx["textura"]] / _dem(c, ctx))
    return max(r, piso) if ctx["riego"] else r

def _evaluar(c, lluvia, ctx):
    if c["tipo"] == "cobertura": return True, "", 1.0
    s = ctx["suelo"]
    if not c["ph_min"] <= s["ph"] <= c["ph_max"]:
        return False, tr(f"el pH {_num(s['ph'])} queda fuera de su rango ({_num(c['ph_min'])} a {_num(c['ph_max'])})",
                         f"pH {_num(s['ph'])} is outside its range ({_num(c['ph_min'])} to {_num(c['ph_max'])})"), 0
    if s["salinidad"] == "alta" and c["tol_salinidad"] == "baja":
        return False, tr("no tolera la salinidad medida", "it does not tolerate the measured salinity"), 0
    r = _ratio(c, lluvia, ctx)
    if r < (.25 if c["tol_sequia"] >= 3 else .4):
        return False, tr(f"pide unos {_dem(c, ctx):.0f} mm de agua (según lo que se seca la tierra en la zona) y solo se esperan unos {lluvia * RETENCION[ctx['textura']]:.0f} mm",
                         f"it needs about {_dem(c, ctx):.0f} mm of water (given how fast the soil dries here) and only about {lluvia * RETENCION[ctx['textura']]:.0f} mm are expected"), r
    return True, "", r

def _prios(prios):
    out = []
    for p in prios or []:
        p = ALIAS.get(p, p)
        if p in PRIORIDADES and p not in out: out.append(p)
    return out[:3] or ["nitrogeno", "agua"]

def _pesos(prios):
    """Cada indicador pesa 1; cada prioridad elegida suma 3. Se normaliza a 1."""
    w = {k: 1.0 for k in IND_KEYS}
    for p in prios: w[p] += 3
    t = sum(w.values())
    return {k: v / t for k, v in w.items()}

# ---------------------------------------------------------------- Datos de clima
def diario(zona_id, mes, anio):
    """Lluvia día por día: real de NASA POWER si ya se descargó ese mes; si no, DE EJEMPLO (se reparte el
    total mensual normal de forma determinista)."""
    cl, ok = clima_de(zona_id)
    n = calendar.monthrange(anio, mes)[1]
    rd = ((_reales(zona_id) or {}).get("diario") or {}).get("PRECTOTCORR") or {}
    reales = [rd.get(f"{anio}{mes:02d}{d:02d}") for d in range(1, n + 1)]
    if sum(v is not None for v in reales) >= n - 2:
        dias = [{"dia": d + 1, "lluvia_mm": round(v, 1) if v is not None else None} for d, v in enumerate(reales)]
        tot = round(sum(v for v in reales if v is not None))
        return {"mes": mes, "dias": dias, "total_mm": tot, "evap_mm": cl["evap_mensual_mm"][mes - 1],
                "dias_con_lluvia": sum(1 for v in reales if v is not None and v >= 1), "ejemplo": False, "real": True,
                "fuente": "NASA POWER"}
    total = cl["lluvia_mensual_mm"][mes - 1]
    rng = random.Random(f"{zona_id}-{mes}")
    prob = min(.75, .12 + total / 260)
    w = [rng.random() ** 2.5 if rng.random() < prob else 0 for _ in range(n)]
    if not any(w): w[rng.randrange(n)] = 1
    tot = sum(w)
    dias = [{"dia": d + 1, "lluvia_mm": round(total * w[d] / tot, 1)} for d in range(n)]
    return {"mes": mes, "dias": dias, "total_mm": total, "evap_mm": cl["evap_mensual_mm"][mes - 1],
            "dias_con_lluvia": sum(1 for x in dias if x["lluvia_mm"] > 0), "ejemplo": True, "real": False}

def reciente(zona_id, hoy):
    """Últimos 6 meses completos: lluvia y temperatura de NASA POWER y verdor de MODIS si ya se descargaron
    (servicio de descarga automática); si falta algún mes, ese mes es DE EJEMPLO y se marca con real=False."""
    cl, ok = clima_de(zona_id)
    R = _reales(zona_id) or {}
    pr, t2 = (R.get("diario") or {}).get("PRECTOTCORR") or {}, (R.get("diario") or {}).get("T2M") or {}
    nd = {}
    for x in R.get("ndvi") or []:
        try: nd.setdefault(x["fecha"][:7], []).append(float(x["ndvi"]))
        except (KeyError, TypeError, ValueError): pass
    out = []
    for k in range(6, 0, -1):
        m = (hoy.month - k - 1) % 12 + 1
        a = hoy.year if hoy.month - k >= 1 else hoy.year - 1
        rng = random.Random(f"{zona_id}-{a}-{m}")
        normal = cl["lluvia_mensual_mm"][m - 1]
        f = _clamp(.55 + .9 * rng.random() + cl["tendencia_lluvia_pct"] / 100, .2, 1.8)
        tn = cl["temp_mensual"][m - 1]
        nn = cl["ndvi_mensual"][m - 1]
        n = calendar.monthrange(a, m)[1]
        ll = [pr[x] for x in (f"{a}{m:02d}{d:02d}" for d in range(1, n + 1)) if x in pr]
        tt = [t2[x] for x in (f"{a}{m:02d}{d:02d}" for d in range(1, n + 1)) if x in t2]
        real = len(ll) >= n - 2 and len(tt) >= n - 2
        nv = nd.get(f"{a}-{m:02d}")
        out.append({"mes": m, "anio": a, "nombre": (MC_EN if _en() else MC)[m - 1], "lluvia_normal_mm": normal, "temp_normal_c": round(tn, 1),
                    "lluvia_mm": round(sum(ll) * n / len(ll)) if real else round(normal * f),
                    "temp_c": round(sum(tt) / len(tt), 1) if real else round(tn + rng.uniform(-.4, .9) + cl["tendencia_temp_c"] * .3, 1),
                    "ndvi": round(sum(nv) / len(nv), 2) if nv else round(nn * _clamp(.78 + .3 * rng.random() + (f - 1) * .12, .5, 1.15), 2),
                    "ndvi_normal": round(nn, 2), "real": real, "ndvi_real": bool(nv)})
    return out, ok

def clima_resumen(cl, rec, hoy):
    """Indicadores de clima para el panel: balance de agua, calor, heladas, extremos y tendencias."""
    m = hoy.month - 1
    prox = [(m + i) % 12 for i in range(2)]
    ll2 = sum(cl["lluvia_mensual_mm"][i] for i in prox)
    ev2 = sum(cl["evap_mensual_mm"][i] for i in prox)
    mc = MC_EN if _en() else MC
    serie = [{"mes": i + 1, "nombre": mc[i], "lluvia": cl["lluvia_mensual_mm"][i], "evap": cl["evap_mensual_mm"][i],
              "balance": cl["lluvia_mensual_mm"][i] - cl["evap_mensual_mm"][i], "tmed": cl["temp_mensual"][i],
              "tmax": cl["tmax_mensual"][i], "tmin": cl["tmin_mensual"][i], "ndvi": cl["ndvi_mensual"][i],
              "dias_lluvia": cl["dias_lluvia_mensual"][i], "dias_calor": cl["dias_calor_mensual"][i], "dias_frio": cl["dias_frio_mensual"][i]} for i in range(12)]
    ult = rec[-1]
    dv = round((ult["ndvi_normal"] - ult["ndvi"]) / ult["ndvi_normal"] * 100) if ult["ndvi_normal"] else 0
    dh, tabs = cl["dias_helada"], cl["tmin_absoluta"]
    helada = "nulo" if dh == 0 and tabs > 5 else "bajo" if dh == 0 else "medio" if dh < 5 else "alto"
    return {"mes_actual": m + 1, "serie": serie,
            "lluvia_mes": cl["lluvia_mensual_mm"][m], "evap_mes": cl["evap_mensual_mm"][m], "temp_mes": cl["temp_mensual"][m],
            "lluvia_anual": cl["lluvia_anual_mm"], "evap_anual": cl["evap_anual_mm"],
            "meses_deficit": sum(1 for x in serie if x["balance"] < 0),
            "ll2": ll2, "ev2": ev2, "cubre_2m": round(100 * ll2 / ev2) if ev2 else 100,
            "estres_termico": {"dias": cl["dias_estres_termico"], "nivel": _niv3(cl["dias_estres_termico"], 15, 45), "tmax": cl["tmax_media"]},
            "helada": {"nivel": helada, "dias": dh, "tmin_abs": tabs, "tmin": cl["tmin_media"]},
            "extremas": {"dias": cl["dias_lluvia_extrema"], "max_dia": cl["lluvia_max_dia_mm"], "nivel": _niv3(cl["dias_lluvia_extrema"], 2, 4)},
            "vegetal": {"ndvi": ult["ndvi"], "normal": ult["ndvi_normal"], "deficit_pct": max(0, dv), "mes": ult["nombre"], "nivel": _niv3(max(0, dv), 10, 25)},
            "tendencia": {"lluvia_pct": cl["tendencia_lluvia_pct"], "temp_c": cl["tendencia_temp_c"], "factor_ano_seco": cl["factor_ano_seco"]},
            "veranillo": {"nivel": cl["riesgo_veranillo"], "dias": cl["dias_veranillo"]},
            "humedad_sat": cl["humedad_suelo_pct"], "pendiente": cl["pendiente_pct"],
            "inicio_lluvias": _mes(cl["inicio_lluvias_mes"] - 1), "inicio_lluvias_mes": cl["inicio_lluvias_mes"],
            "mes": dict(serie[m], nombre_largo=_mes(m)), "umbral_calor": UMBRAL_CALOR, "umbral_frio": UMBRAL_FRIO}

# ---------------------------------------------------------------- Panel de control
def salud_suelo(s):
    ph = float(s["ph"]); niv = {"bajo": .25, "medio": .7, "alto": .9}
    h = float(s.get("humedad_pct", 25))
    vals = (_clamp(1 - max(0, abs(ph - 6.5) - .5) / 2.5), niv[s["n"]], niv[s["p"]], niv[s["k"]],
            1.0 if s["salinidad"] == "normal" else .2, _clamp(1 - max(0, 20 - h, h - 35) / 15))
    nombres = [tr(a, b) for a, b in (("Acidez (pH)", "Acidity (pH)"), ("Nitrógeno", "Nitrogen"), ("Fósforo", "Phosphorus"),
                                     ("Potasio", "Potassium"), ("Salinidad", "Salinity"), ("Humedad", "Moisture"))]
    valor = round(100 * sum(p * v for p, v in zip((.25, .2, .15, .15, .15, .1), vals)))
    fac = [{"nombre": n, "estado": "bien" if v >= .7 else "atención" if v >= .45 else "crítico"} for n, v in zip(nombres, vals)]
    peores = [n for v, n in sorted(zip(vals, nombres)) if v < .7][:2]
    txt = (tr("Lo que más lo afecta: ", "What affects it most: ") + tr(" y ", " and ").join(peores).lower() + ".") if peores \
        else tr("Todos los factores están en buen estado.", "All factors are in good shape.")
    return {"valor": valor, "semaforo": _sem(valor), "texto": txt, "factores": fac}

def panel(zona_id, suelo, textura, riego, hoy=None):
    hoy = hoy or date.today()
    z = zona(zona_id)
    cl, ok = clima_de(zona_id)
    rec, _ = reciente(zona_id, hoy)
    C = clima_resumen(cl, rec, hoy)
    riego = bool(z["riego"] if riego is None else riego)
    textura = textura if textura in RETENCION else z["suelo"]
    u3 = rec[-3:]
    a, n = sum(r["lluvia_mm"] for r in u3), sum(r["lluvia_normal_mm"] for r in u3)
    dev = round((a - n) / n * 100) if n else 0
    prox = [cl["lluvia_mensual_mm"][(hoy.month - 1 + i) % 12] for i in range(2)]
    dt = round(rec[-1]["temp_c"] - rec[-1]["temp_normal_c"], 1)
    ll2, ev2 = C["ll2"], C["ev2"]
    al = []
    if dev <= -25: al.append(("alerta" if dev <= -40 else "atención", tr("Lluvia por debajo de lo normal", "Rain below normal"),
                              tr(f"En los últimos 3 meses llovió {abs(dev)}% menos de lo normal ({a} mm frente a {n} mm).",
                                 f"In the last 3 months it rained {abs(dev)}% less than normal ({a} mm vs {n} mm).")))
    if dev >= 30: al.append(("alerta" if dev >= 50 else "atención", tr("Exceso de lluvia", "Too much rain"),
                             tr(f"En los últimos 3 meses llovió {dev}% más de lo normal ({a} mm frente a {n} mm).",
                                f"In the last 3 months it rained {dev}% more than normal ({a} mm vs {n} mm).")))
    if ev2 and ll2 < .5 * ev2:
        al.append(("alerta" if ll2 < .2 * ev2 else "atención", tr("La tierra se secará más de lo que llueve", "The soil will dry more than it rains"),
                   tr(f"En los próximos 2 meses se esperan unos {ll2} mm de lluvia y la tierra perdería unos {ev2} mm al secarse.",
                      f"In the next 2 months about {ll2} mm of rain are expected and the soil would lose about {ev2} mm as it dries.") +
                   (tr(" Planea el riego.", " Plan your irrigation.") if riego else tr(" Sin riego, evita cultivos que pidan mucha agua.", " Without irrigation, avoid thirsty crops."))))
    if max(prox) > 250: al.append(("atención", tr("Lluvias fuertes esperadas", "Heavy rain expected"),
                                   tr(f"Un mes puede llegar a {max(prox)} mm; cuida el drenaje y las laderas.", f"One month may reach {max(prox)} mm; take care of drainage and slopes.")))
    if C["vegetal"]["nivel"] != "bajo":
        al.append(("alerta" if C["vegetal"]["nivel"] == "alto" else "atención", tr("Plantas con estrés", "Stressed plants"),
                   tr(f"El verdor de la zona (NDVI) en {C['vegetal']['mes'].lower()} estuvo {C['vegetal']['deficit_pct']}% por debajo de lo normal.",
                      f"Vegetation greenness (NDVI) in {C['vegetal']['mes']} was {C['vegetal']['deficit_pct']}% below normal.")))
    if C["estres_termico"]["nivel"] == "alto": al.append(("atención", tr("Mucho calor extremo", "Lots of extreme heat"),
        tr(f"Unos {C['estres_termico']['dias']} días al año pasan de 35 °C; las plantas sufren y gastan más agua.",
           f"About {C['estres_termico']['dias']} days a year go above 35 °C; plants suffer and use more water.")))
    elif dt >= 1: al.append(("atención", tr("Calor sobre lo normal", "Warmer than normal"),
                             tr(f"El último mes estuvo {_num(dt)} °C por encima de lo normal.", f"Last month was {_num(dt)} °C above normal.")))
    if C["extremas"]["nivel"] == "alto": al.append(("atención", tr("Aguaceros muy fuertes", "Very heavy downpours"),
        tr(f"Cada año caen unos {_num(C['extremas']['dias'])} aguaceros de más de 50 mm en un día (el mayor: {C['extremas']['max_dia']} mm). Protege el suelo con cobertura.",
           f"Each year about {_num(C['extremas']['dias'])} downpours exceed 50 mm in a day (largest: {C['extremas']['max_dia']} mm). Keep the soil covered.")))
    if C["helada"]["nivel"] in ("medio", "alto"): al.append(("alerta" if C["helada"]["nivel"] == "alto" else "atención", tr("Riesgo de heladas", "Frost risk"),
        tr(f"Hay unos {_num(C['helada']['dias'])} días al año con temperatura bajo 0 °C.", f"About {_num(C['helada']['dias'])} days a year drop below 0 °C.")))
    if cl["riesgo_veranillo"] == "alto": al.append(("atención", tr("Riesgo alto de veranillo", "High risk of dry spells"),
        tr(f"Pueden venir hasta {cl['dias_veranillo']} días secos seguidos en plena temporada de lluvias.",
           f"Up to {cl['dias_veranillo']} dry days in a row can happen in the middle of the rainy season.")))
    if cl["humedad_suelo_pct"] < 20: al.append(("atención", tr("Humedad del suelo baja", "Low soil moisture"),
        tr(f"El satélite mide {cl['humedad_suelo_pct']}% de humedad en la zona de raíces.", f"The satellite measures {cl['humedad_suelo_pct']}% moisture in the root zone.")))
    orden = {"alerta": 0, "atención": 1}
    al.sort(key=lambda x: orden[x[0]])
    alertas = [{"nivel": x[0], "titulo": x[1], "texto": x[2]} for x in al[:5]] or \
              [{"nivel": "bien", "titulo": tr("Sin alertas", "No alerts"), "texto": tr("El clima reciente está dentro de lo normal para tu zona.", "Recent weather is within normal for your area.")}]
    ries_s = round(_clamp((max(0, -dev) * 1.2 + {"alto": 25, "medio": 12}.get(cl["riesgo_veranillo"], 0) + (15 if cl["humedad_suelo_pct"] < 25 else 0)
                           + (15 if ev2 and ll2 < .5 * ev2 else 0)) / 100) * 100)
    ries_e = round(_clamp((max(0, dev) * 1.2 + (20 if max(prox) > 250 else 0) + (10 if textura == "arcilloso" else 0) + 6 * cl["dias_lluvia_extrema"]) / 100) * 100)
    ries_c = round(_clamp(cl["dias_estres_termico"] / 120 + max(0, dt) * .1) * 100)
    ries_h = {"nulo": 0, "bajo": 10, "medio": 45, "alto": 80}[C["helada"]["nivel"]]
    niv = lambda v: "bajo" if v < 30 else "medio" if v < 60 else "alto"
    h = float(suelo.get("humedad_pct", 25)); t = float(suelo.get("temp_suelo_c", 29))
    sal = salud_suelo(suelo)
    riesgos = {"sequia": ries_s, "exceso": ries_e, "calor": ries_c, "helada": ries_h}
    peor = max(riesgos, key=riesgos.get)
    NOMR = {"sequia": ("la sequía", "drought"), "exceso": ("el exceso de lluvia", "too much rain"), "calor": ("el calor", "heat"), "helada": ("las heladas", "frost")}
    agua = min(100, C["cubre_2m"])
    anillos = {"suelo": {"valor": sal["valor"], "texto": sal["texto"]},
               "agua": {"valor": agua, "texto": tr(f"La lluvia de los próximos 2 meses cubre el {C['cubre_2m']}% del agua que pierde la tierra al secarse.",
                                                   f"Rain in the next 2 months covers {C['cubre_2m']}% of the water the soil loses as it dries.")
                        + (tr(" Con riego puedes cubrir el resto.", " With irrigation you can cover the rest.") if riego and agua < 100 else "")},
               "clima": {"valor": 100 - riesgos[peor], "texto": tr(f"El mayor riesgo ahora es {NOMR[peor][0]}.", f"The biggest risk now is {NOMR[peor][1]}.")
                         if riesgos[peor] >= 30 else tr("El clima está favorable.", "Weather is favorable.")}}
    return {"salud": sal, "anillos": anillos, "clima": C, "riego": riego,
            "humedad": {"suelo": h, "satelite": cl["humedad_suelo_pct"], "estado": "baja" if h < 20 else "alta" if h > 35 else "adecuada"},
            "temperatura": {"suelo": t, "aire": cl["temp_media"], "anomalia": dt, "estado": "baja" if t < 22 else "alta" if t > 33 else "adecuada"},
            "alertas": alertas, "n_alertas": sum(1 for x in alertas if x["nivel"] != "bien"),
            "riesgos": {k: {"valor": v, "nivel": niv(v)} for k, v in riesgos.items()},
            "reciente": rec, "reciente_real": all(r["real"] for r in rec), "ejemplo": not ok,
            "fuente_clima": cl.get("fuente"), "prestado_de": cl.get("prestado_de"),
            "campos_ejemplo": cl.get("campos_ejemplo") or []}

# ---------------------------------------------------------------- Recomendaciones
def _ctx(z, cl, suelo, textura, riego):
    return {"suelo": dict(suelo, ph=float(suelo["ph"])), "textura": textura if textura in RETENCION else z["suelo"],
            "riego": bool(z["riego"] if riego is None else riego), "f_evap": cl["f_evap"]}

def _erosion(cl):
    return _clamp(cl["pendiente_pct"] / 30 + .25 * min(1, cl["dias_lluvia_extrema"] / 6))

def _lista_ultimos(ultimos):
    if not ultimos: return []
    return [ultimos] if isinstance(ultimos, str) else [u for u in ultimos if u]

def recomendar(zona_id, suelo, prioridades=("nitrogeno", "agua"), ultimos=None, riego=None, textura=None, top=3):
    z = zona(zona_id)
    cl, cl_ok = clima_de(zona_id)
    prios = _prios(prioridades)
    w = _pesos(prios)
    ctx = _ctx(z, cl, suelo, textura, riego)
    s = ctx["suelo"]
    cult = {c["cultivo"]: c for c in db.consultar("SELECT * FROM cultivos")}
    ults = [cult[u] for u in _lista_ultimos(ultimos) if u in cult]
    nbajo, ladera = s["n"] == "bajo", cl["pendiente_pct"] > 15
    notas, desc = [], {}

    def anotar(c, razon, ok):
        d = desc.setdefault(c["cultivo"], {"ok": False, "razones": []})
        d["ok"] = d["ok"] or ok
        if razon and razon not in d["razones"]: d["razones"].append(razon)

    opciones = []
    for t in range(3):
        off, ll, lista = TEMPORADAS[t][2], _lluvia(cl, TEMPORADAS[t][2]), []
        for c in cult.values():
            if c["tipo"] == "cobertura":
                if t == 2: lista.append((c, 1.0, 0))
                continue
            if c["ciclo_dias"] > LARGO: continue
            ok, razon, r = _evaluar(c, ll, ctx)
            anotar(c, razon, ok)
            if ok: lista.append((c, r, ll))
        opciones.append(lista)
    largos = []
    for c in cult.values():
        if c["ciclo_dias"] > LARGO:
            ll = _lluvia(cl, 0, 12) * .85
            ok, razon, r = _evaluar(c, ll, ctx)
            anotar(c, razon, ok)
            if ok: largos.append((c, r, ll))

    def valido(seq, act):
        for a, b in zip(seq, seq[1:]):
            if a["familia"] == b["familia"]: return False
            if a["tipo"] == "cereal" and b["tipo"] not in LEGUM + ("cobertura",): return False
        if "ultimo" in act:
            for u in ults:
                if u["familia"] == seq[0]["familia"] or (u["tipo"] == "cereal" and seq[0]["tipo"] not in LEGUM): return False
        if "n_bajo" in act and nbajo and not seq[0]["fija_n"]: return False
        if "cobertura" in act and len(seq) == 3:
            cub = [c["cobertura"] >= .6 for c in seq]
            if (not ctx["riego"] and not cub[2]) or (ladera and not any(cub)): return False
        return True

    cand = []
    for act in ({"n_bajo", "cobertura", "ultimo"}, {"n_bajo", "cobertura"}, {"cobertura"}, set()):
        for combo in product(*opciones):
            seq = [x[0] for x in combo]
            if valido(seq, act): cand.append((seq, [x[1] for x in combo], [x[2] for x in combo], False))
        for c, r, ll in largos:
            if valido([c], act): cand.append(([c, c, c], [r] * 3, [ll] * 3, True))
        if cand:
            if nbajo and "n_bajo" not in act: notas.append(tr("No hay leguminosa viable para empezar con el suelo y el clima de este lote; se relajó esa regla.",
                                                             "No legume can start the rotation with this soil and climate; that rule was relaxed."))
            if "cobertura" not in act: notas.append(tr("No se pudo exigir cobertura en el verano con las condiciones dadas.", "Ground cover in the dry season could not be required with these conditions."))
            if ults and "ultimo" not in act: notas.append(tr("No se pudo evitar repetir la familia de lo que sembraste antes.", "It was not possible to avoid repeating the family of what you planted before."))
            break
    if not cand:
        notas.append(tr("Con este suelo y este clima no hay una rotación de 3 temporadas que cumpla las reglas. Mira qué cultivos quedaron por fuera y por qué.",
                        "With this soil and climate no 3-season rotation meets the rules. See which crops were left out and why."))

    fs = cl["factor_ano_seco"]
    calor = .05 if cl["dias_estres_termico"] > 40 else 0
    eros = _erosion(cl)
    res = []
    for seq, ratios, lluvias, largo in cand:
        n, bloques = NIVEL[s["n"]], []
        for i, c in enumerate(seq[:1] if largo else seq):
            n0 = n
            n = _clamp(n + .3 * c["fija_n"] - .25 * c["demanda_n"] * (1.5 if largo else 1))
            if c["tipo"] == "cobertura": base = seco = 1.0
            else:
                base = _ratio(c, lluvias[i] * fs, ctx, .7)
                seco = _clamp(base + .1 * (c["tol_sequia"] - 1) - calor)
            bloques.append({"c": c, "ll": lluvias[i], "r": ratios[i], "base": base, "seco": seco, "n0": n0, "n1": n})
        k = len(bloques)
        avg = lambda f: sum(f(b["c"]) for b in bloques) / k
        cob = avg(lambda c: c["cobertura"])
        ind = {"agua": 100 * sum(b["r"] for b in bloques) / k,
               "nitrogeno": 100 * (.6 * n + .4 * avg(lambda c: c["fija_n"])),
               "erosion": 100 * (.5 * cob + .5 * (1 - eros * (1 - cob))),
               "materia_organica": 100 * avg(lambda c: c["materia_organica"]),
               "forraje": 100 * avg(lambda c: c["forraje"]),
               "mercado": 100 * avg(lambda c: .5 * c["mercado"] + .5 * c["ingreso_rel"]),
               "resiliencia": 100 * sum(b["seco"] for b in bloques) / k}
        res.append((sum(w[x] * ind[x] for x in ind), seq, ind, largo, bloques, n, cob))
    res.sort(key=lambda r: -r[0])

    elegidos = []
    for r in res:
        if all(sum(a["cultivo"] != b["cultivo"] for a, b in zip(r[1], e[1])) >= 2 for e in elegidos): elegidos.append(r)
        if len(elegidos) == top: break
    for r in res:
        if len(elegidos) == top: break
        if r not in elegidos: elegidos.append(r)

    planes = []
    m0 = cl["inicio_lluvias_mes"] - 1
    for puntaje, seq, ind, largo, bloques, n_fin, cob in elegidos:
        items = []
        for i, b in enumerate(bloques):
            c = b["c"]; off = 0 if largo else TEMPORADAS[i][2]
            dur = (int(c["ciclo_dias"]) - 1) // 30 if c["ciclo_dias"] else 0
            items.append({"temporada": tr("Todo el año", "All year") if largo else _temp(i), "cultivo": c["cultivo"], "nombre": _nom(c),
                          "icono": c["icono"], "tipo": c["tipo"], "ocupa": 3 if largo else 1, "siembra": _mes(m0 + off),
                          "cosecha": _mes(m0 + off + dur) if c["ciclo_dias"] else None, "off": off, "dur": dur,
                          "por_que": _porque(c, bloques[i - 1]["c"] if i else (ults[0] if ults else None), i, nbajo, ladera, largo, prios)})
        expl = _explicaciones(bloques, ind, n_fin, cob, eros, s, cl, ctx, fs, calor, largo)
        crono = _cronograma(items, m0)
        planes.append({"puntaje": round(puntaje), "semaforo": _sem(puntaje), "secuencia": items,
                       "indicadores": {k: {"valor": round(v), "semaforo": _sem(v), "explicacion": expl[k]} for k, v in ind.items()},
                       "beneficio": _beneficio(ind, prios), "cronograma": crono,
                       "informe": {"temporadas": [{"temporada": it["temporada"], "cultivo": it["nombre"], "icono": it["icono"], "tipo": it["tipo"],
                                                   "siembra": it["siembra"], "cosecha": it["cosecha"], "lluvia_mm": round(b["ll"] * RETENCION[ctx["textura"]]),
                                                   "agua_mm": round(_dem(b["c"], ctx)), "cubierto_pct": round(b["r"] * 100), "n_despues": _nivel(b["n1"])}
                                                  for it, b in zip(items, bloques)],
                                   "nitrogeno": [s["n"]] + [_nivel(b["n1"]) for b in bloques], "cronograma": crono}})

    fuera = [{"cultivo": _nom(cult[k]), "icono": cult[k]["icono"], "razon": d["razones"][0]} for k, d in desc.items() if not d["ok"] and d["razones"]]
    ejemplo = (not cl_ok) or not all(c["verificado"] for c in db.consultar("SELECT verificado FROM cultivos"))
    return {"zona": z["nombre"], "prioridades": prios, "pesos": w, "riego": ctx["riego"], "textura": ctx["textura"], "planes": planes,
            "descartados": fuera, "notas": notas, "datos_de_ejemplo": ejemplo}

def _beneficio(ind, prios):
    k = max(prios, key=lambda p: ind[p])
    return {"clave": k, "nombre": tr(*NOM_IND[k]), "valor": round(ind[k])}

def _porque(c, prev, i, nbajo, ladera, largo, prios):
    n = _nom(c)
    if c["tipo"] == "cobertura":
        return tr("Deja el rastrojo como cobertura: protege " + ("la ladera de la erosión." if ladera else "el suelo del sol y del viento en el verano."),
                  "Leave crop residue as cover: it protects " + ("the slope from erosion." if ladera else "the soil from sun and wind in the dry season."))
    if largo: return tr(f"{n} ocupa todo el año: tiene su propio ciclo largo y no se mezcla con otras siembras.", f"{n} takes the whole year: it has its own long cycle.")
    if c["fija_n"] and i == 0 and nbajo: return tr(f"{n} va primero porque tu nitrógeno está bajo y esta leguminosa lo repone.", f"{n} goes first because your nitrogen is low and this legume restores it.")
    if c["tipo"] == "abono_verde": return tr(f"{n} repone nitrógeno y mucha materia orgánica; se incorpora al suelo antes de que semille.",
                                             f"{n} restores nitrogen and lots of organic matter; it is worked into the soil before it sets seed.")
    if c["fija_n"] and "forraje" in prios and c["forraje"] >= .7: return tr(f"{n} repone nitrógeno y su follaje sirve de comida para los animales.", f"{n} restores nitrogen and its leaves feed your animals.")
    if c["fija_n"]: return tr(f"{n} repone nitrógeno y cubre el suelo.", f"{n} restores nitrogen and covers the soil.")
    if prev and prev["fija_n"] and c["demanda_n"] >= .6: return tr(f"{n} aprovecha el nitrógeno que dejó {_nom(prev).lower()}.", f"{n} uses the nitrogen left by {_nom(prev).lower()}.")
    if "forraje" in prios and c["forraje"] >= .7: return tr(f"{n} deja rastrojo que sirve de forraje para tus animales.", f"{n} leaves residue that works as forage for your animals.")
    if c["tol_sequia"] >= 3: return tr(f"{n} aguanta bien la poca lluvia de esta temporada.", f"{n} copes well with the little rain of this season.")
    if c["mercado"] >= .7: return tr(f"{n} se vende bien en la zona y su ciclo cabe en la temporada.", f"{n} sells well locally and its cycle fits the season.")
    return tr(f"{n} cabe en la temporada y cambia de familia respecto a la anterior.", f"{n} fits the season and changes family from the previous crop.")

def _explicaciones(bl, ind, n_fin, cob, eros, s, cl, ctx, fs, calor, largo):
    nom = lambda b: _nom(b["c"])
    lista = lambda campo: ", ".join(f"{nom(b)} {round(b['c'][campo] * 100)}" for b in bl)
    fij = [nom(b) for b in bl if b["c"]["fija_n"]]
    gas = [nom(b) for b in bl if b["c"]["demanda_n"] >= .6]
    nit = [tr(f"Nitrógeno: empiezas en nivel {s['n']} y al terminar la secuencia quedaría en nivel {_nivel(n_fin)}.",
              f"Nitrogen: you start at {_nt(s['n'])} level and would end at {_nt(_nivel(n_fin))} level.")]
    nit.append(tr("Fijan nitrógeno del aire en el suelo: ", "Fix nitrogen from the air into the soil: ") + ", ".join(fij) + "." if fij
               else tr("Ningún cultivo de esta secuencia fija nitrógeno.", "No crop in this sequence fixes nitrogen."))
    if gas: nit.append(tr("Gastan bastante nitrógeno: ", "Use a lot of nitrogen: ") + ", ".join(gas) + ".")
    ero = [tr(f"El suelo queda cubierto cerca del {round(cob * 100)}% del tiempo.", f"The soil stays covered about {round(cob * 100)}% of the time.")]
    if cl["pendiente_pct"] > 5: ero.append(tr(f"Con una pendiente de {_num(cl['pendiente_pct'])}%, el riesgo de erosión queda {_nivel_eros(eros * (1 - cob))}.",
                                              f"With a {_num(cl['pendiente_pct'])}% slope, erosion risk is {_nt(_nivel_eros(eros * (1 - cob)))}."))
    de = cl["dias_lluvia_extrema"]
    if de: ero.append(tr((f"Caen unos {_num(de)} aguaceros al año" if de >= 2 else "Cae cerca de un aguacero al año") + " de más de 50 mm; sobre suelo desnudo arrastran tierra.",
                         (f"About {_num(de)} downpours a year" if de >= 2 else "About one downpour a year") + " exceed 50 mm; on bare soil they wash it away."))
    mo = [tr("Aporte de materia orgánica de cada cultivo (0 a 100): ", "Organic matter contribution of each crop (0 to 100): ") + lista("materia_organica") + ".",
          tr("Dejar los residuos en el lote y no quemarlos sube la materia orgánica.", "Leaving residues in the field instead of burning them raises organic matter.")]
    fo = [tr("Valor como comida para animales (0 a 100): ", "Value as animal feed (0 to 100): ") + lista("forraje") + "."]
    buenos = [nom(b) for b in bl if b["c"]["forraje"] >= .7]
    if buenos: fo.append(tr("Dejan buen forraje (rastrojo o follaje): ", "Leave good forage (residue or leaves): ") + ", ".join(buenos) + ".")
    me = [tr("Qué tanto se vende en la zona (0 a 100): ", "How well it sells locally (0 to 100): ") + lista("mercado") + ".",
          tr("Se combina con el valor relativo de cada cultivo. No es un precio: ajústalo con los precios reales de tu zona.",
             "It is combined with each crop's relative value. It is not a price: adjust it with real local prices.")]
    if any(b["c"]["mercado"] == 0 for b in bl): me.append(tr("El rastrojo y el abono verde cuidan el suelo, pero no se venden; por eso bajan el promedio.",
                                                            "Residue cover and green manure protect the soil but are not sold, so they lower the average."))
    agua = []
    for i, b in enumerate(bl):
        if b["c"]["tipo"] == "cobertura": continue
        tn = tr("Todo el año", "All year") if largo else _temp(i)
        agua.append(tr(f"{tn}: se esperan unos {b['ll'] * RETENCION[ctx['textura']]:.0f} mm y {nom(b)} pide unos {_dem(b['c'], ctx):.0f} mm; queda cubierto el {round(b['r'] * 100)}%.",
                       f"{tn}: about {b['ll'] * RETENCION[ctx['textura']]:.0f} mm expected and {nom(b)} needs about {_dem(b['c'], ctx):.0f} mm; {round(b['r'] * 100)}% covered."))
    fe = ctx["f_evap"]
    agua.append(tr(f"En tu zona la tierra pierde al secarse unos {cl['evap_anual_mm']} mm al año frente a {cl['lluvia_anual_mm']} mm de lluvia. ",
                   f"In your area the soil loses about {cl['evap_anual_mm']} mm per year as it dries, vs {cl['lluvia_anual_mm']} mm of rain. ") +
                (tr("Ese secado es parecido al de referencia, así que el agua que pide cada cultivo casi no cambia.",
                    "That is close to the reference, so each crop's water need barely changes.") if abs(fe - 1) < .03 else
                 tr(f"Por eso el agua que pide cada cultivo {'sube' if fe > 1 else 'baja'} un {round(abs(fe - 1) * 100)}%.",
                    f"So each crop's water need goes {'up' if fe > 1 else 'down'} by {round(abs(fe - 1) * 100)}%.")))
    agua.append(tr("Con riego, ninguna temporada baja del 85%, por eso el valor sube.", "With irrigation no season falls below 85%, so the value goes up.") if ctx["riego"]
                else tr("Sin riego, solo cuenta la lluvia que cae en cada temporada.", "Without irrigation, only the rain of each season counts."))
    tol = [nom(b) for b in bl if b["c"]["tol_sequia"] >= 3 and b["c"]["tipo"] != "cobertura"]
    sen = [nom(b) for b in bl if b["c"]["tol_sequia"] <= 1]
    pr = round(sum(b["base"] for b in bl) / len(bl) * 100)
    res = [tr(f"En un año seco (llueve cerca del {round(fs * 100)}% de lo normal) la lluvia cubriría en promedio el {pr}% del agua que piden estos cultivos.",
              f"In a dry year (about {round(fs * 100)}% of normal rain) rain would cover on average {pr}% of what these crops need.")]
    if tol: res.append(tr("Aguantan bien la sequía: ", "Drought tolerant: ") + ", ".join(tol) + ".")
    if sen: res.append(tr("Son sensibles a la sequía: ", "Drought sensitive: ") + ", ".join(sen) + ".")
    if calor: res.append(tr(f"Hay {cl['dias_estres_termico']} días al año sobre 35 °C; eso resta puntos.", f"There are {cl['dias_estres_termico']} days a year above 35 °C; that lowers the score."))
    return {"agua": agua, "nitrogeno": nit, "erosion": ero, "materia_organica": mo, "forraje": fo, "mercado": me, "resiliencia": res}

def _cronograma(items, m0):
    ev, filas = [], []
    for i, it in enumerate(items):
        n, t, off, dur = it["nombre"], it["tipo"], it["off"], it["dur"]
        if t == "cobertura":
            ev.append((off, "cobertura", tr("Dejar el rastrojo como cobertura sobre el suelo", "Leave the crop residue as ground cover"), n))
            filas.append({"nombre": n, "icono": it["icono"], "tipo": t, "inicio": off, "largo": 4})
        else:
            if t == "abono_verde":
                ev.append((off, "cobertura", tr(f"Sembrar {n.lower()} (cultivo de cobertura)", f"Sow {n.lower()} (cover crop)"), n))
                ev.append((off + dur, "cobertura", tr(f"Incorporar el {n.lower()} al suelo antes de que semille", f"Work the {n.lower()} into the soil before it sets seed"), n))
            else:
                ev.append((off, "siembra", tr(f"Sembrar {n}", f"Sow {n}"), n)); ev.append((off + dur, "cosecha", tr(f"Cosechar {n}", f"Harvest {n}"), n))
            filas.append({"nombre": n, "icono": it["icono"], "tipo": t, "inicio": off, "largo": dur + 1})
        if i + 1 < len(items): ev.append((items[i + 1]["off"], "cambio", tr(f"Cambio de cultivo: de {n} a {items[i + 1]['nombre']}", f"Crop change: from {n} to {items[i + 1]['nombre']}"), items[i + 1]["nombre"]))
        elif len(items) == 1: ev.append((off + dur + 1, "cambio", tr("Fin del ciclo largo: prepara el cambio de cultivo", "End of the long cycle: get ready to change crops"), n))
        else: ev.append((12, "cambio", tr("Nuevo ciclo: revisa tus datos y empieza otra rotación", "New cycle: review your data and start another rotation"), n))
    ev.sort(key=lambda e: e[0])
    return {"m0": m0 % 12,
            "eventos": [{"mes": _mes(m0 + r), "off": r, "tipo": tp, "texto": tx, "cultivo": cu} for r, tp, tx, cu in ev],
            "gantt": {"meses": [(MC_EN if _en() else MC)[(m0 + k) % 12] for k in range(12)], "filas": filas}}

# ---------------------------------------------------------------- Simulador (Proyección)
def _eval_seq(seq, largo, ctx, cl, n0, anios):
    fs = cl["factor_ano_seco"]; calor = .05 if cl["dias_estres_termico"] > 40 else 0
    eros = _erosion(cl)
    bl = seq[:1] if largo else seq
    dem = defi = cob = seco = mo = 0.0
    for i, c in enumerate(bl):
        if c is None: seco += .4; continue                     # temporada con la tierra destapada
        ll = _lluvia(cl, 0, 12) * .85 if largo else _lluvia(cl, TEMPORADAS[i][2])
        d = _dem(c, ctx) if _productivo(c) else 0.0             # el abono verde y el rastrojo no se riegan
        dem += d; defi += max(0, d - ll * RETENCION[ctx["textura"]])
        cob += c["cobertura"]; mo += c["materia_organica"]
        seco += 1.0 if c["tipo"] == "cobertura" else _clamp(_ratio(c, ll * fs, ctx, .7) + .1 * (c["tol_sequia"] - 1) - calor)
    k = len(bl); cob /= k; seco /= k; mo /= k
    # Nitrógeno: cada temporada el suelo se acerca un poco al nivel que deja ese cultivo (no salta de golpe a 0 o 100)
    vel = .35 if largo else .2
    n, serie = n0, [round(n0 * 100)]
    for _ in range(anios):
        for c in bl:
            n = _clamp(n - .01) if c is None else _clamp(n + vel * (_meta_n(c) - n))
        serie.append(round(n * 100))
    ret, sq, ex = 100 * (.5 * serie[1] / 100 + .5 * cob), 100 * seco, 100 * (1 - (.2 + .8 * eros) * (1 - cob))
    return {"demanda_mm": round(dem), "deficit_mm": round(defi), "cobertura_pct": round(cob * 100), "materia_organica": round(mo * 100), "n_serie": serie,
            "indices": {"retencion": round(ret), "sequia": round(sq), "lluvias": round(ex), "total": round((ret + sq + ex) / 3)}}

def simular(zona_id, suelo, textura, riego, secuencia, ultimos, ha, anios):
    z = zona(zona_id)
    cl, ok = clima_de(zona_id)
    cult = {c["cultivo"]: c for c in db.consultar("SELECT * FROM cultivos")}
    ctx = _ctx(z, cl, suelo, textura, riego)
    cs = [cult[x] for x in secuencia if x in cult]
    largo = len(cs) == 1
    plan = cs * 3 if largo else cs
    ul = [u for u in _lista_ultimos(ultimos) if u in cult]
    # Práctica de comparación: el monocultivo de cereal, que es lo que se rota en la región. Si el agricultor venía
    # sembrando maíz o arroz, se compara con seguir sembrando ese cereal; si venía de otro cultivo, con maíz.
    b = cult[ul[0]] if ul and cult[ul[0]]["tipo"] == "cereal" else cult["maiz"]
    bl_largo = b["ciclo_dias"] > LARGO
    # Comparación justa: "sin rotar" siembra el mismo cultivo en las MISMAS temporadas en que el plan produce.
    # Donde el plan pone abono verde o rastrojo, sin rotar deja la tierra destapada. Con riego, sin rotar siembra todo el año.
    if bl_largo or ctx["riego"]: base = [b, b, b]
    elif largo: base = [b, b, None]
    else: base = [b if _productivo(c) else None for c in plan]
    if not any(base): base = [b, b, None]
    n0 = NIVEL[ctx["suelo"]["n"]]
    P, B = _eval_seq(plan, largo, ctx, cl, n0, anios), _eval_seq(base, bl_largo, ctx, cl, n0, anios)
    ah_def = B["deficit_mm"] - P["deficit_mm"]
    m3ha, m3 = ah_def * 10, ah_def * 10 * ha
    nb = _nom(b)
    tempos = [_temp(i) for i, c in enumerate(base) if c is not None]
    base_txt = tr(f"Sembrar solo {nb.lower()} todo el año", f"Planting only {nb.lower()} all year") if len(tempos) == 3 else \
        tr(f"Sembrar solo {nb.lower()} en las mismas temporadas ({', '.join(t.lower() for t in tempos)})",
           f"Planting only {nb.lower()} in the same seasons ({', '.join(t.lower() for t in tempos)})")
    nota = None
    if ah_def < 0:
        prod = [c for c in (plan[:1] if largo else plan) if _productivo(c)]
        mayor = max(prod, key=lambda c: c["agua_mm"]) if prod else None
        mejoras = []
        if P["n_serie"][-1] > B["n_serie"][-1]: mejoras.append(tr("deja más nitrógeno", "leaves more nitrogen"))
        if P["cobertura_pct"] > B["cobertura_pct"]: mejoras.append(tr("cubre más el suelo", "covers the soil more"))
        if P["indices"]["total"] > B["indices"]["total"]: mejoras.append(tr("aguanta mejor los años secos", "copes better with dry years"))
        nota = tr(f"Esta rotación pide más agua que sembrar solo {nb.lower()}" + (f" porque incluye {_nom(mayor).lower()}" if mayor and mayor["agua_mm"] > b["agua_mm"] else "") + "."
                  + (f" A cambio, {' y '.join(mejoras)}." if mejoras else ""),
                  f"This rotation needs more water than planting only {nb.lower()}" + (f" because it includes {_nom(mayor).lower()}" if mayor and mayor["agua_mm"] > b["agua_mm"] else "") + "."
                  + (f" In return, it {' and '.join(mejoras)}." if mejoras else ""))
    pct = round(100 * ah_def / B["deficit_mm"]) if B["deficit_mm"] else (0 if not P["deficit_mm"] else None)
    nota_largo = tr(f"Esta recomendación es un solo cultivo de todo el año ({_nom(cs[0]).lower()}). La proyección supone que lo repites cada año; "
                    "para rotar de verdad, alterna con una leguminosa como frijol o guandul al año siguiente.",
                    f"This recommendation is a single all-year crop ({_nom(cs[0]).lower()}). The outlook assumes you repeat it every year; "
                    "to truly rotate, alternate with a legume such as beans or pigeon pea the next year.") if largo and cs else None
    return {"base": dict(B, cultivo=nb, descripcion=base_txt), "plan": P, "nota_agua": nota, "nota_largo": nota_largo,
            "ahorro": {"demanda_mm": B["demanda_mm"] - P["demanda_mm"], "deficit_mm": ah_def, "m3_ha": round(m3ha), "m3_total": round(m3), "pct_deficit": pct},
            "proyeccion": {"anios": list(range(anios + 1)), "agua_acum_m3": [round(m3 * a) for a in range(anios + 1)], "n_plan": P["n_serie"], "n_base": B["n_serie"]},
            "ha": ha, "anios": anios, "ejemplo": not ok, "riego": ctx["riego"]}
