"""Motor de reglas transparente (sin ML).
Clima (NASA): lluvia, temperatura media, máxima y mínima, estrés térmico, riesgo de heladas, evaporación
(Hargreaves-Samani, FAO-56), humedad del suelo, lluvias extremas, verdor y estrés vegetal (NDVI), veranillo,
pendiente y tendencias de largo plazo.
Suelo: pH, N-P-K, humedad, temperatura, salinidad y textura.
Cultivos: ciclo, agua, pH, familia, fijación de nitrógeno, cobertura, forraje, materia orgánica y mercado.
Prioridades del agricultor: agua, forraje, nitrógeno, erosión, materia orgánica y mercado."""
import calendar, json, math, random
from datetime import date
from itertools import product
import db

MESES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
MC = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
TEMPORADAS = [("Primeras lluvias", 0), ("Segundas lluvias", 4), ("Verano", 8)]
PRIORIDADES = ("agua", "forraje", "nitrogeno", "erosion", "materia_organica", "mercado")
ALIAS = {"suelo": "nitrogeno", "ingreso": "mercado"}          # nombres de la versión anterior
IND_KEYS = ("agua", "nitrogeno", "erosion", "materia_organica", "forraje", "mercado", "resiliencia")
NOM_IND = {"agua": "Uso del agua", "nitrogeno": "Nitrógeno", "erosion": "Frena la erosión", "materia_organica": "Materia orgánica",
           "forraje": "Forraje", "mercado": "Mercado", "resiliencia": "Aguante en años secos"}
NIVEL = {"bajo": .2, "medio": .5, "alto": .8}
RETENCION = {"arenoso": .85, "franco": 1.0, "arcilloso": 1.1}
LARGO = 135
LEGUM = ("leguminosa", "abono_verde")
ET0_REF = 5.0   # mm/día, evaporación típica de tierras bajas tropicales: referencia para ajustar el agua que pide cada cultivo

def _clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def _nivel(x): return "bajo" if x < .35 else "medio" if x < .65 else "alto"
def _nivel_eros(x): return "bajo" if x < .15 else "medio" if x < .35 else "alto"
def _niv3(v, a, b): return "bajo" if v < a else "medio" if v < b else "alto"
def _sem(x): return "verde" if x >= 70 else "amarillo" if x >= 45 else "rojo"
def _mes(n): return MESES[n % 12]

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
    """Agrega los campos derivados que falten (series mensuales de temperatura y evaporación)."""
    cl = dict(cl)
    onda = [math.cos(2 * math.pi * (m - 3) / 12) for m in range(12)]
    if "temp_mensual" not in cl:
        cl["temp_mensual"] = [round(cl["temp_media"] + 1.3 * o, 1) for o in onda]
        cl["tmax_mensual"] = [round(cl.get("tmax_media", cl["temp_media"] + 5.5) + 1.5 * o, 1) for o in onda]
        cl["tmin_mensual"] = [round(cl.get("tmin_media", cl["temp_media"] - 5) + .8 * o, 1) for o in onda]
    if "evap_mensual_mm" not in cl:
        cl["evap_mensual_mm"] = [round(et0(cl["temp_mensual"][m], cl["tmax_mensual"][m], cl["tmin_mensual"][m], lat, m + 1)
                                       * calendar.monthrange(2023, m + 1)[1]) for m in range(12)]
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

def clima_de(zona_id):
    f = db.consultar("SELECT datos, verificado FROM clima WHERE zona_id=?", (zona_id,))
    if not f: return None, False
    z = db.consultar("SELECT lat FROM zonas WHERE id=?", (zona_id,))
    return _completar(json.loads(f[0]["datos"]), float(z[0]["lat"]) if z else 10.0), bool(f[0]["verificado"])

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
        return False, f"el pH {s['ph']:.1f} queda fuera de su rango ({c['ph_min']:g}–{c['ph_max']:g})", 0
    if s["salinidad"] == "alta" and c["tol_salinidad"] == "baja":
        return False, "no tolera la salinidad medida", 0
    r = _ratio(c, lluvia, ctx)
    if r < (.25 if c["tol_sequia"] >= 3 else .4):
        return False, f"pide unos {_dem(c, ctx):.0f} mm de agua (con la evaporación de la zona) y solo se esperan unos {lluvia * RETENCION[ctx['textura']]:.0f} mm", r
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
    """Lluvia y verdor día por día. DE EJEMPLO: se reparte el total mensual de forma determinista."""
    cl, ok = clima_de(zona_id)
    n = calendar.monthrange(anio, mes)[1]
    total = cl["lluvia_mensual_mm"][mes - 1]
    rng = random.Random(f"{zona_id}-{mes}")
    prob = min(.75, .12 + total / 260)
    w = [rng.random() ** 2.5 if rng.random() < prob else 0 for _ in range(n)]
    if not any(w): w[rng.randrange(n)] = 1
    tot, nd, dias = sum(w), cl["ndvi_mensual"], []
    for d in range(n):
        pos = (mes - 1) + (d + .5) / n - .5
        a = math.floor(pos); f = pos - a
        dias.append({"dia": d + 1, "lluvia_mm": round(total * w[d] / tot, 1),
                     "ndvi": round(nd[a % 12] * (1 - f) + nd[(a + 1) % 12] * f, 2)})
    return {"mes": mes, "dias": dias, "total_mm": total, "evap_mm": cl["evap_mensual_mm"][mes - 1],
            "dias_con_lluvia": sum(1 for x in dias if x["lluvia_mm"] > 0), "ejemplo": not ok}

def reciente(zona_id, hoy):
    """Últimos 6 meses completos (lluvia, temperatura y verdor reales vs normales). DE EJEMPLO."""
    cl, ok = clima_de(zona_id)
    out = []
    for k in range(6, 0, -1):
        m = (hoy.month - k - 1) % 12 + 1
        a = hoy.year if hoy.month - k >= 1 else hoy.year - 1
        rng = random.Random(f"{zona_id}-{a}-{m}")
        normal = cl["lluvia_mensual_mm"][m - 1]
        f = _clamp(.55 + .9 * rng.random() + cl["tendencia_lluvia_pct"] / 100, .2, 1.8)
        tn = cl["temp_mensual"][m - 1]
        nn = cl["ndvi_mensual"][m - 1]
        nv = nn * _clamp(.78 + .3 * rng.random() + (f - 1) * .12, .5, 1.15)
        out.append({"mes": m, "anio": a, "nombre": MC[m - 1], "lluvia_mm": round(normal * f), "lluvia_normal_mm": normal,
                    "temp_c": round(tn + rng.uniform(-.4, .9) + cl["tendencia_temp_c"] * .3, 1), "temp_normal_c": round(tn, 1),
                    "ndvi": round(nv, 2), "ndvi_normal": round(nn, 2)})
    return out, ok

def clima_resumen(cl, rec, hoy):
    """Indicadores de clima para el panel: balance de agua, calor, heladas, extremos, estrés vegetal y tendencias."""
    m = hoy.month - 1
    prox = [(m + i) % 12 for i in range(2)]
    ll2 = sum(cl["lluvia_mensual_mm"][i] for i in prox)
    ev2 = sum(cl["evap_mensual_mm"][i] for i in prox)
    serie = [{"mes": i + 1, "nombre": MC[i], "lluvia": cl["lluvia_mensual_mm"][i], "evap": cl["evap_mensual_mm"][i],
              "balance": cl["lluvia_mensual_mm"][i] - cl["evap_mensual_mm"][i], "tmed": cl["temp_mensual"][i],
              "tmax": cl["tmax_mensual"][i], "tmin": cl["tmin_mensual"][i], "ndvi": cl["ndvi_mensual"][i]} for i in range(12)]
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
            "vegetal": {"ndvi": ult["ndvi"], "normal": ult["ndvi_normal"], "deficit_pct": max(0, dv), "mes": ult["nombre"],
                        "nivel": _niv3(max(0, dv), 10, 25)},
            "tendencia": {"lluvia_pct": cl["tendencia_lluvia_pct"], "temp_c": cl["tendencia_temp_c"], "factor_ano_seco": cl["factor_ano_seco"]},
            "veranillo": {"nivel": cl["riesgo_veranillo"], "dias": cl["dias_veranillo"]},
            "humedad_sat": cl["humedad_suelo_pct"], "pendiente": cl["pendiente_pct"],
            "inicio_lluvias": MESES[cl["inicio_lluvias_mes"] - 1]}

# ---------------------------------------------------------------- Panel de control
def salud_suelo(s):
    ph = float(s["ph"]); niv = {"bajo": .25, "medio": .7, "alto": .9}
    h = float(s.get("humedad_pct", 25))
    vals = (_clamp(1 - max(0, abs(ph - 6.5) - .5) / 2.5), niv[s["n"]], niv[s["p"]], niv[s["k"]],
            1.0 if s["salinidad"] == "normal" else .2, _clamp(1 - max(0, 20 - h, h - 35) / 15))
    nombres = ("Acidez (pH)", "Nitrógeno", "Fósforo", "Potasio", "Salinidad", "Humedad")
    valor = round(100 * sum(p * v for p, v in zip((.25, .2, .15, .15, .15, .1), vals)))
    fac = [{"nombre": n, "estado": "bien" if v >= .7 else "atención" if v >= .45 else "crítico"} for n, v in zip(nombres, vals)]
    peores = [n for v, n in sorted(zip(vals, nombres)) if v < .7][:2]
    txt = ("Lo que más lo afecta: " + " y ".join(peores).lower() + ".") if peores else "Todos los factores están en buen estado."
    return {"valor": valor, "semaforo": _sem(valor), "texto": txt, "factores": fac}

def panel(zona_id, suelo, textura, riego, hoy=None):
    hoy = hoy or date.today()
    z = db.consultar("SELECT * FROM zonas WHERE id=?", (zona_id,))[0]
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
    if dev <= -25: al.append(("alerta" if dev <= -40 else "atención", "Lluvia por debajo de lo normal", f"En los últimos 3 meses llovió {abs(dev)}% menos de lo normal ({a} mm frente a {n} mm)."))
    if dev >= 30: al.append(("alerta" if dev >= 50 else "atención", "Exceso de lluvia", f"En los últimos 3 meses llovió {dev}% más de lo normal ({a} mm frente a {n} mm)."))
    if ev2 and ll2 < .5 * ev2:
        al.append(("alerta" if ll2 < .2 * ev2 else "atención", "Se evapora más de lo que llueve",
                   f"En los próximos 2 meses se esperan unos {ll2} mm de lluvia y se evaporarían unos {ev2} mm." +
                   (" Planea el riego." if riego else " Sin riego, evita cultivos que pidan mucha agua.")))
    if max(prox) > 250: al.append(("atención", "Lluvias fuertes esperadas", f"Un mes puede llegar a {max(prox)} mm; cuida el drenaje y las laderas."))
    if C["vegetal"]["nivel"] != "bajo":
        al.append(("alerta" if C["vegetal"]["nivel"] == "alto" else "atención", "Plantas con estrés",
                   f"El verdor de la zona (NDVI) en {C['vegetal']['mes'].lower()} estuvo {C['vegetal']['deficit_pct']}% por debajo de lo normal."))
    if C["estres_termico"]["nivel"] == "alto": al.append(("atención", "Mucho calor extremo", f"Unos {C['estres_termico']['dias']} días al año pasan de 35 °C; las plantas sufren y gastan más agua."))
    elif dt >= 1: al.append(("atención", "Calor sobre lo normal", f"El último mes estuvo {str(dt).replace('.', ',')} °C por encima de lo normal."))
    if C["extremas"]["nivel"] == "alto": al.append(("atención", "Aguaceros muy fuertes", f"Cada año caen unos {C['extremas']['dias']} aguaceros de más de 50 mm en un día (el mayor: {C['extremas']['max_dia']} mm). Protege el suelo con cobertura."))
    if C["helada"]["nivel"] in ("medio", "alto"): al.append(("alerta" if C["helada"]["nivel"] == "alto" else "atención", "Riesgo de heladas", f"Hay unos {C['helada']['dias']} días al año con temperatura bajo 0 °C."))
    if cl["riesgo_veranillo"] == "alto": al.append(("atención", "Riesgo alto de veranillo", f"Pueden venir hasta {cl['dias_veranillo']} días secos seguidos en plena temporada de lluvias."))
    if cl["humedad_suelo_pct"] < 20: al.append(("atención", "Humedad del suelo baja", f"El satélite mide {cl['humedad_suelo_pct']}% de humedad en la zona de raíces."))
    orden = {"alerta": 0, "atención": 1}
    al.sort(key=lambda x: orden[x[0]])
    alertas = [{"nivel": x[0], "titulo": x[1], "texto": x[2]} for x in al[:5]] or \
              [{"nivel": "bien", "titulo": "Sin alertas", "texto": "El clima reciente está dentro de lo normal para tu zona."}]
    ries_s = round(_clamp((max(0, -dev) * 1.2 + {"alto": 25, "medio": 12}.get(cl["riesgo_veranillo"], 0) + (15 if cl["humedad_suelo_pct"] < 25 else 0)
                           + (15 if ev2 and ll2 < .5 * ev2 else 0)) / 100) * 100)
    ries_e = round(_clamp((max(0, dev) * 1.2 + (20 if max(prox) > 250 else 0) + (10 if textura == "arcilloso" else 0)
                           + 6 * cl["dias_lluvia_extrema"]) / 100) * 100)
    ries_c = round(_clamp(cl["dias_estres_termico"] / 120 + max(0, dt) * .1) * 100)
    ries_h = {"nulo": 0, "bajo": 10, "medio": 45, "alto": 80}[C["helada"]["nivel"]]
    niv = lambda v: "bajo" if v < 30 else "medio" if v < 60 else "alto"
    h = float(suelo.get("humedad_pct", 25)); t = float(suelo.get("temp_suelo_c", 29))
    sal = salud_suelo(suelo)
    riesgos = {"sequia": ries_s, "exceso": ries_e, "calor": ries_c, "helada": ries_h}
    peor = max(riesgos, key=riesgos.get)
    NOMR = {"sequia": "la sequía", "exceso": "el exceso de lluvia", "calor": "el calor", "helada": "las heladas"}
    agua = min(100, C["cubre_2m"])
    anillos = {"suelo": {"valor": sal["valor"], "texto": sal["texto"]},
               "agua": {"valor": agua, "texto": f"La lluvia de los próximos 2 meses cubre el {C['cubre_2m']}% del agua que se evapora."
                        + (" Con riego puedes cubrir el resto." if riego and agua < 100 else "")},
               "clima": {"valor": 100 - riesgos[peor], "texto": f"El mayor riesgo ahora es {NOMR[peor]}." if riesgos[peor] >= 30 else "El clima está favorable."}}
    return {"salud": sal, "anillos": anillos, "clima": C, "riego": riego,
            "humedad": {"suelo": h, "satelite": cl["humedad_suelo_pct"], "estado": "baja" if h < 20 else "alta" if h > 35 else "adecuada"},
            "temperatura": {"suelo": t, "aire": cl["temp_media"], "anomalia": dt, "estado": "baja" if t < 22 else "alta" if t > 33 else "adecuada"},
            "alertas": alertas, "n_alertas": sum(1 for x in alertas if x["nivel"] != "bien"),
            "riesgos": {k: {"valor": v, "nivel": niv(v)} for k, v in riesgos.items()},
            "reciente": rec, "ejemplo": not ok}

# ---------------------------------------------------------------- Recomendaciones
def _ctx(z, cl, suelo, textura, riego):
    return {"suelo": dict(suelo, ph=float(suelo["ph"])), "textura": textura if textura in RETENCION else z["suelo"],
            "riego": bool(z["riego"] if riego is None else riego), "f_evap": cl["f_evap"]}

def _erosion(cl):
    return _clamp(cl["pendiente_pct"] / 30 + .25 * min(1, cl["dias_lluvia_extrema"] / 6))

def recomendar(zona_id, suelo, prioridades=("nitrogeno", "agua"), ultimo=None, riego=None, textura=None, top=3):
    z = db.consultar("SELECT * FROM zonas WHERE id=?", (zona_id,))[0]
    cl, cl_ok = clima_de(zona_id)
    prios = _prios(prioridades)
    w = _pesos(prios)
    ctx = _ctx(z, cl, suelo, textura, riego)
    s = ctx["suelo"]
    cult = {c["cultivo"]: c for c in db.consultar("SELECT * FROM cultivos")}
    ult = cult.get(ultimo)
    nbajo, pend = s["n"] == "bajo", cl["pendiente_pct"]
    ladera = pend > 15
    notas, desc = [], {}

    def anotar(c, razon, ok):
        d = desc.setdefault(c["cultivo"], {"ok": False, "razones": []})
        d["ok"] = d["ok"] or ok
        if razon and razon not in d["razones"]: d["razones"].append(razon)

    opciones = []
    for t, (nombre, off) in enumerate(TEMPORADAS):
        ll, lista = _lluvia(cl, off), []
        for c in cult.values():
            if c["tipo"] == "cobertura":
                if t == 2: lista.append((c, 1.0, 0))
                continue
            if c["ciclo_dias"] > LARGO: continue
            ok, razon, r = _evaluar(c, ll, ctx)
            anotar(c, f"{nombre.lower()}: {razon}" if razon else "", ok)
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
        if ult and (ult["familia"] == seq[0]["familia"] or (ult["tipo"] == "cereal" and seq[0]["tipo"] not in LEGUM)): return False
        if "n_bajo" in act and nbajo and not seq[0]["fija_n"]: return False
        if "cobertura" in act and len(seq) == 3:
            cub = [c["cobertura"] >= .6 for c in seq]
            if (not ctx["riego"] and not cub[2]) or (ladera and not any(cub)): return False
        return True

    cand = []
    for act in ({"n_bajo", "cobertura"}, {"cobertura"}, set()):
        for combo in product(*opciones):
            seq = [x[0] for x in combo]
            if valido(seq, act): cand.append((seq, [x[1] for x in combo], [x[2] for x in combo], False))
        for c, r, ll in largos:
            if valido([c], act): cand.append(([c, c, c], [r] * 3, [ll] * 3, True))
        if cand:
            if nbajo and "n_bajo" not in act: notas.append("No hay leguminosa viable para empezar con el suelo y el clima de este lote; se relajó esa regla.")
            if "cobertura" not in act: notas.append("No se pudo exigir cobertura en el verano con las condiciones dadas.")
            break
    if not cand:
        notas.append("Con este suelo y este clima no hay una rotación de 3 temporadas que cumpla las reglas. Mira qué cultivos quedaron por fuera y por qué.")

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
            c = b["c"]; off = 0 if largo else TEMPORADAS[i][1]
            dur = (int(c["ciclo_dias"]) - 1) // 30 if c["ciclo_dias"] else 0
            items.append({"temporada": "Todo el año" if largo else TEMPORADAS[i][0], "cultivo": c["cultivo"], "nombre": c["nombre"],
                          "icono": c["icono"], "tipo": c["tipo"], "ocupa": 3 if largo else 1, "siembra": _mes(m0 + off),
                          "cosecha": _mes(m0 + off + dur) if c["ciclo_dias"] else None, "off": off, "dur": dur,
                          "por_que": _porque(c, bloques[i - 1]["c"] if i else ult, i, nbajo, ladera, largo, prios)})
        reglas = ["Nunca repite la misma familia dos temporadas seguidas"]
        if any(a["tipo"] == "cereal" and b["tipo"] in LEGUM for a, b in zip(seq, seq[1:])): reglas.append("Después del cereal va una leguminosa")
        if nbajo and seq[0]["fija_n"]: reglas.append("Con nitrógeno bajo, empieza con una leguminosa")
        if any(c["cobertura"] >= .6 for c in seq): reglas.append("Deja cobertura para que el suelo no quede desnudo")
        if largo: reglas.append("Cultivo de ciclo largo: ocupa las tres temporadas")
        expl = _explicaciones(bloques, ind, n_fin, cob, eros, s, cl, ctx, fs, calor, largo)
        crono = _cronograma(items, m0)
        planes.append({"puntaje": round(puntaje), "semaforo": _sem(puntaje), "secuencia": items, "reglas": reglas,
                       "indicadores": {k: {"valor": round(v), "semaforo": _sem(v), "explicacion": expl[k]} for k, v in ind.items()},
                       "beneficio": _beneficio(ind, prios),
                       "cronograma": crono,
                       "informe": _informe(items, bloques, s, cl, ctx, ladera, calor, largo, expl, reglas, crono, cl_ok)})

    fuera = [{"cultivo": cult[k]["nombre"], "icono": cult[k]["icono"], "razon": d["razones"][0].split(": ", 1)[-1]}
             for k, d in desc.items() if not d["ok"] and d["razones"]]
    ejemplo = (not cl_ok) or not all(c["verificado"] for c in db.consultar("SELECT verificado FROM cultivos"))
    return {"zona": z["nombre"], "prioridades": prios, "pesos": w, "riego": ctx["riego"], "textura": ctx["textura"], "planes": planes,
            "descartados": fuera, "notas": notas, "datos_de_ejemplo": ejemplo}

def _beneficio(ind, prios):
    """El indicador más alto entre las prioridades elegidas (para la medalla de la tarjeta)."""
    k = max(prios, key=lambda p: ind[p])
    return {"clave": k, "nombre": NOM_IND[k], "valor": round(ind[k])}

def _porque(c, prev, i, nbajo, ladera, largo, prios):
    n = c["nombre"]
    if c["tipo"] == "cobertura":
        return "Deja el rastrojo como cobertura: protege " + ("la ladera de la erosión." if ladera else "el suelo del sol y del viento en el verano.")
    if largo: return f"{n} ocupa todo el año: tiene su propio ciclo largo y no se mezcla con otras siembras."
    if c["fija_n"] and i == 0 and nbajo: return f"{n} va primero porque tu nitrógeno está bajo y esta leguminosa lo repone."
    if c["tipo"] == "abono_verde": return f"{n} repone nitrógeno y mucha materia orgánica; se incorpora al suelo antes de que semille."
    if c["fija_n"] and "forraje" in prios and c["forraje"] >= .7: return f"{n} repone nitrógeno y su follaje sirve de comida para los animales."
    if c["fija_n"]: return f"{n} repone nitrógeno y cubre el suelo."
    if prev and prev["fija_n"] and c["demanda_n"] >= .6: return f"{n} aprovecha el nitrógeno que dejó {prev['nombre'].lower()}."
    if "forraje" in prios and c["forraje"] >= .7: return f"{n} deja rastrojo que sirve de forraje para tus animales."
    if c["tol_sequia"] >= 3: return f"{n} aguanta bien la poca lluvia de esta temporada."
    if c["mercado"] >= .7: return f"{n} se vende bien en la zona y su ciclo cabe en la temporada."
    return f"{n} cabe en la temporada y cambia de familia respecto a la anterior."

def _explicaciones(bl, ind, n_fin, cob, eros, s, cl, ctx, fs, calor, largo):
    nom = lambda b: b["c"]["nombre"]
    lista = lambda campo: ", ".join(f"{nom(b)} {round(b['c'][campo] * 100)}" for b in bl)
    fij = [nom(b) for b in bl if b["c"]["fija_n"]]
    gas = [nom(b) for b in bl if b["c"]["demanda_n"] >= .6]
    nit = [f"Nitrógeno: empiezas en nivel {s['n']} y al terminar la secuencia quedaría en nivel {_nivel(n_fin)}."]
    nit.append(("Fijan nitrógeno del aire en el suelo: " + ", ".join(fij) + ".") if fij else "Ningún cultivo de esta secuencia fija nitrógeno.")
    if gas: nit.append("Gastan bastante nitrógeno: " + ", ".join(gas) + ".")
    ero = [f"El suelo queda cubierto cerca del {round(cob * 100)}% del tiempo."]
    if cl["pendiente_pct"] > 5: ero.append(f"Con una pendiente de {cl['pendiente_pct']:g}%, el riesgo de erosión queda {_nivel_eros(eros * (1 - cob))}.")
    de = cl["dias_lluvia_extrema"]
    if de: ero.append((f"Caen unos {de:g} aguaceros al año" if de >= 2 else "Cae cerca de un aguacero al año") + " de más de 50 mm; sobre suelo desnudo arrastran tierra.")
    mo = ["Aporte de materia orgánica de cada cultivo (0 a 100): " + lista("materia_organica") + ".",
          "Dejar los residuos en el lote y no quemarlos sube la materia orgánica."]
    fo = ["Valor como comida para animales (0 a 100): " + lista("forraje") + "."]
    buenos = [nom(b) for b in bl if b["c"]["forraje"] >= .7]
    if buenos: fo.append("Dejan buen forraje (rastrojo o follaje): " + ", ".join(buenos) + ".")
    me = ["Qué tanto se vende en la zona (0 a 100): " + lista("mercado") + ".",
          "Se combina con el valor relativo de cada cultivo. No es un precio: ajústalo con los precios reales de tu zona."]
    if any(b["c"]["mercado"] == 0 for b in bl): me.append("El rastrojo y el abono verde cuidan el suelo, pero no se venden; por eso bajan el promedio.")
    agua = []
    for i, b in enumerate(bl):
        if b["c"]["tipo"] == "cobertura": continue
        tn = "Todo el año" if largo else TEMPORADAS[i][0]
        agua.append(f"{tn}: se esperan unos {b['ll'] * RETENCION[ctx['textura']]:.0f} mm y {nom(b)} pide unos {_dem(b['c'], ctx):.0f} mm; queda cubierto el {round(b['r'] * 100)}%.")
    fe = ctx["f_evap"]
    agua.append(f"En tu zona se evaporan unos {cl['evap_anual_mm']} mm al año frente a {cl['lluvia_anual_mm']} mm de lluvia. " +
                ("Esa evaporación es parecida a la de referencia, así que el agua que pide cada cultivo casi no cambia." if abs(fe - 1) < .03 else
                 f"Por eso el agua que pide cada cultivo {'sube' if fe > 1 else 'baja'} un {round(abs(fe - 1) * 100)}%."))
    agua.append("Con riego, ninguna temporada baja del 85%, por eso el valor sube." if ctx["riego"] else "Sin riego, solo cuenta la lluvia que cae en cada temporada.")
    tol = [nom(b) for b in bl if b["c"]["tol_sequia"] >= 3 and b["c"]["tipo"] != "cobertura"]
    sen = [nom(b) for b in bl if b["c"]["tol_sequia"] <= 1]
    res = [f"En un año seco (llueve cerca del {round(fs * 100)}% de lo normal) la lluvia cubriría en promedio el {round(sum(b['base'] for b in bl) / len(bl) * 100)}% del agua que piden estos cultivos."]
    if tol: res.append("Aguantan bien la sequía: " + ", ".join(tol) + ".")
    if sen: res.append("Son sensibles a la sequía: " + ", ".join(sen) + ".")
    if calor: res.append(f"Hay {cl['dias_estres_termico']} días al año sobre 35 °C; eso resta puntos.")
    return {"agua": agua, "nitrogeno": nit, "erosion": ero, "materia_organica": mo, "forraje": fo, "mercado": me, "resiliencia": res}

def _cronograma(items, m0):
    ev, filas = [], []
    for i, it in enumerate(items):
        n, t, off, dur = it["nombre"], it["tipo"], it["off"], it["dur"]
        if t == "cobertura":
            ev.append((off, "cobertura", "Dejar el rastrojo como cobertura sobre el suelo", n)); filas.append({"nombre": n, "icono": it["icono"], "tipo": t, "inicio": off, "largo": 4})
        else:
            if t == "abono_verde":
                ev.append((off, "cobertura", f"Sembrar {n.lower()} (cultivo de cobertura)", n))
                ev.append((off + dur, "cobertura", f"Incorporar el {n.lower()} al suelo antes de que semille", n))
            else:
                ev.append((off, "siembra", f"Sembrar {n}", n)); ev.append((off + dur, "cosecha", f"Cosechar {n}", n))
            filas.append({"nombre": n, "icono": it["icono"], "tipo": t, "inicio": off, "largo": dur + 1})
        if i + 1 < len(items): ev.append((items[i + 1]["off"], "cambio", f"Cambio de cultivo: de {n} a {items[i + 1]['nombre']}", items[i + 1]["nombre"]))
        elif len(items) == 1: ev.append((off + dur + 1, "cambio", "Fin del ciclo largo: prepara el cambio de cultivo", n))
        else: ev.append((12, "cambio", "Nuevo ciclo: revisa tus datos y empieza otra rotación", n))
    ev.sort(key=lambda e: e[0])
    return {"eventos": [{"mes": _mes(m0 + r) + (" (año siguiente)" if r >= 12 else ""), "tipo": tp, "texto": tx, "cultivo": cu} for r, tp, tx, cu in ev],
            "gantt": {"meses": [MC[(m0 + k) % 12] for k in range(12)], "filas": filas}}

def _informe(items, bl, s, cl, ctx, ladera, calor, largo, expl, reglas, crono, cl_ok):
    fil = [{"temporada": it["temporada"], "cultivo": it["nombre"], "icono": it["icono"], "tipo": it["tipo"], "siembra": it["siembra"], "cosecha": it["cosecha"],
            "lluvia_mm": round(b["ll"] * RETENCION[ctx["textura"]]), "agua_mm": round(_dem(b["c"], ctx)), "cubierto_pct": round(b["r"] * 100),
            "n_despues": _nivel(b["n1"])} for it, b in zip(items, bl)]
    ri = []
    if cl["riesgo_veranillo"] != "bajo": ri.append(f"Veranillo con riesgo {cl['riesgo_veranillo']}: pueden venir hasta {cl['dias_veranillo']} días secos seguidos en plena temporada.")
    if cl["evap_anual_mm"] > cl["lluvia_anual_mm"]: ri.append(f"Se evapora más de lo que llueve: unos {cl['evap_anual_mm']} mm al año frente a {cl['lluvia_anual_mm']} mm de lluvia.")
    if ladera: ri.append(f"Terreno de ladera ({cl['pendiente_pct']:g}% de pendiente): la lluvia fuerte puede arrastrar suelo.")
    if cl["dias_lluvia_extrema"] >= 3: ri.append(f"Aguaceros fuertes: unos {cl['dias_lluvia_extrema']} días al año pasan de 50 mm (el mayor, {cl['lluvia_max_dia_mm']} mm).")
    if calor: ri.append(f"Calor: unos {cl['dias_estres_termico']} días al año pasan de 35 °C.")
    if cl["dias_helada"]: ri.append(f"Heladas: unos {cl['dias_helada']} días al año bajan de 0 °C.")
    if cl["tendencia_lluvia_pct"] < 0: ri.append(f"La lluvia de la zona bajó cerca de {abs(cl['tendencia_lluvia_pct'])}% en los últimos 20 años.")
    if s["salinidad"] == "alta": ri.append("Salinidad alta: vigila el agua de riego y evita dejar el suelo desnudo.")
    if not ctx["riego"]: ri.append("Sin riego, la cosecha depende de que la lluvia llegue a tiempo.")
    cu = []
    if any(b["c"]["fija_n"] for b in bl): cu.append("Deja los residuos de la leguminosa en el lote: así el nitrógeno pasa al siguiente cultivo.")
    if any(b["c"]["tipo"] == "cereal" for b in bl): cu.append("Cuando coseches el cereal, siembra pronto la leguminosa para no dejar el suelo desnudo.")
    if any(b["c"]["forraje"] >= .7 for b in bl): cu.append("Si usas el rastrojo o el follaje como forraje, deja una parte en el lote para no perder materia orgánica.")
    if any(b["c"]["tipo"] == "cobertura" for b in bl): cu.append("Deja el rastrojo sobre el suelo en el verano; no lo quemes.")
    if largo and ladera: cu.append("Los cultivos de ciclo largo cubren poco el suelo: en ladera conviene sembrar franjas con cobertura.")
    cu.append("Confirma estas recomendaciones con un agrónomo o con un análisis de laboratorio antes de sembrar.")
    sup = ["La lluvia esperada sale del promedio histórico de la zona, no de un pronóstico.",
           f"La evaporación se calcula con la fórmula de Hargreaves (FAO-56) a partir de la temperatura máxima, mínima y media; el agua que pide cada cultivo se ajusta frente a una referencia de {str(ET0_REF).replace('.', ',')} mm por día.",
           "Forraje, materia orgánica y mercado son valores relativos de 0 a 100 que deben ajustarse con datos de la zona.",
           "Los pesos de cada factor son una propuesta inicial y se pueden ajustar."]
    if not cl_ok: sup.insert(0, "Los datos de clima, cultivos y suelo son de ejemplo y deben validarse.")
    return {"temporadas": fil, "nitrogeno": [s["n"]] + [x["n_despues"] for x in fil], "riesgos": ri or ["No se detectan riesgos fuertes con los datos disponibles."],
            "cuidados": cu, "supuestos": sup, "reglas": reglas, "factores": expl, "cronograma": crono}

# ---------------------------------------------------------------- Simulador de impacto
def _eval_seq(seq, largo, ctx, cl, n0, anios):
    fs = cl["factor_ano_seco"]; calor = .05 if cl["dias_estres_termico"] > 40 else 0
    eros = _erosion(cl)
    bl = seq[:1] if largo else seq
    dem = defi = cob = seco = mo = 0.0
    for i, c in enumerate(bl):
        if c is None: seco += .4; continue
        ll = _lluvia(cl, 0, 12) * .85 if largo else _lluvia(cl, TEMPORADAS[i][1])
        d = _dem(c, ctx)
        dem += d; defi += max(0, d - ll * RETENCION[ctx["textura"]])
        cob += c["cobertura"]; mo += c["materia_organica"]
        seco += 1.0 if c["tipo"] == "cobertura" else _clamp(_ratio(c, ll * fs, ctx, .7) + .1 * (c["tol_sequia"] - 1) - calor)
    k = len(bl); cob /= k; seco /= k; mo /= k
    n, serie = n0, [round(n0 * 100)]
    for _ in range(anios):
        for c in bl:
            n = _clamp(n - .01) if c is None else _clamp(n + .5 * (.3 * c["fija_n"] - .25 * c["demanda_n"] * (1.5 if largo else 1)))
        serie.append(round(n * 100))
    ret, sq, ex = 100 * (.5 * serie[1] / 100 + .5 * cob), 100 * seco, 100 * (1 - (.2 + .8 * eros) * (1 - cob))
    return {"demanda_mm": round(dem), "deficit_mm": round(defi), "cobertura_pct": round(cob * 100), "materia_organica": round(mo * 100), "n_serie": serie,
            "indices": {"retencion": round(ret), "sequia": round(sq), "lluvias": round(ex), "total": round((ret + sq + ex) / 3)}}

def simular(zona_id, suelo, textura, riego, secuencia, ultimo, ha, anios):
    z = db.consultar("SELECT * FROM zonas WHERE id=?", (zona_id,))[0]
    cl, ok = clima_de(zona_id)
    cult = {c["cultivo"]: c for c in db.consultar("SELECT * FROM cultivos")}
    ctx = _ctx(z, cl, suelo, textura, riego)
    s = ctx["suelo"]
    cs = [cult[x] for x in secuencia if x in cult]
    largo = len(cs) == 1
    plan = cs * 3 if largo else cs
    b = cult.get(ultimo) or cult["maiz"]
    bl_largo = b["ciclo_dias"] > LARGO
    tres = bl_largo or ctx["riego"]
    base = [b, b, b] if tres else [b, b, None]
    n0 = NIVEL[s["n"]]
    P, B = _eval_seq(plan, largo, ctx, cl, n0, anios), _eval_seq(base, bl_largo, ctx, cl, n0, anios)
    ah_dem, ah_def = B["demanda_mm"] - P["demanda_mm"], B["deficit_mm"] - P["deficit_mm"]
    m3ha, m3 = ah_def * 10, ah_def * 10 * ha
    msg = []
    mil = lambda x: f"{round(x):,}".replace(",", ".")
    if ah_def > 0: msg.append(f"Con esta rotación necesitarías unos {ah_def} mm menos de agua de riego al año: {mil(m3ha)} m³ por hectárea, {mil(m3)} m³ en tus {str(ha).replace('.', ',').removesuffix(',0')} ha.")
    elif ah_def < 0: msg.append(f"Esta rotación pide unos {abs(ah_def)} mm más de riego al año que sembrar lo mismo; su beneficio está en el suelo y la resiliencia.")
    else: msg.append("El agua de riego necesaria es parecida a la de sembrar lo mismo; el beneficio está en el suelo y la resiliencia.")
    d = P["indices"]["total"] - B["indices"]["total"]
    msg.append(f"La resiliencia climática {'mejora' if d >= 0 else 'baja'} {abs(d)} puntos frente a la práctica de comparación.")
    msg.append(f"En {anios} años, el nitrógeno del suelo quedaría en nivel {_nivel(P['n_serie'][-1] / 100)} con la rotación y en nivel {_nivel(B['n_serie'][-1] / 100)} con la práctica de comparación.")
    return {"base": dict(B, nombre=f"Sembrar {b['nombre'].lower()} " + ("todo el año" if bl_largo else "en las tres temporadas, sin rotar" if ctx["riego"] else "en las dos temporadas de lluvia y dejar el suelo descubierto en verano")),
            "plan": P, "ahorro": {"demanda_mm": ah_dem, "deficit_mm": ah_def, "m3_ha": round(m3ha), "m3_total": round(m3),
                                  "pct_deficit": round(100 * ah_def / B["deficit_mm"]) if B["deficit_mm"] else 0},
            "proyeccion": {"anios": list(range(anios + 1)), "agua_acum_m3": [round(m3 * a) for a in range(anios + 1)], "n_plan": P["n_serie"], "n_base": B["n_serie"]},
            "mensajes": msg, "ha": ha, "anios": anios,
            "supuestos": ["Práctica de comparación: repetir tu último cultivo (o maíz si no indicaste uno) sin rotar, en las mismas temporadas que tu lote puede sembrar: las tres con riego, solo las dos de lluvia sin riego.",
                          "El suelo descubierto cuenta 40 puntos de resistencia a la sequía.",
                          "El déficit de agua es lo que la lluvia esperada no alcanza a cubrir; se cubre con riego o se pierde cosecha.",
                          "El agua que pide cada cultivo se ajusta por la evaporación de la zona.",
                          "Las proyecciones son estimaciones con reglas simples" + (" y datos de ejemplo." if not ok else ".")],
            "ejemplo": not ok}
