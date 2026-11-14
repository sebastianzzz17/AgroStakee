import json
from datetime import date
from flask import Flask, jsonify, request, send_from_directory
from services import motor
import db

app = Flask(__name__)
db.init()

def _suelo(s):
    return {"ph": float(s["ph"]), "n": s.get("n", "medio"), "p": s.get("p", "medio"), "k": s.get("k", "medio"),
            "humedad_pct": float(s.get("humedad_pct", 25)), "temp_suelo_c": float(s.get("temp_suelo_c", 29)),
            "salinidad": s.get("salinidad", "normal")}

@app.route("/")
def index():
    return send_from_directory("templates", "index.html")

@app.route("/api/zonas")
def zonas():
    out = []
    for z in db.consultar("SELECT * FROM zonas"):
        z["clima"], z["clima_verificado"] = motor.clima_de(z["id"])
        z["riego"] = bool(z["riego"])
        out.append(z)
    return jsonify(out)

@app.route("/api/perfiles")
def perfiles():
    return jsonify([json.loads(p["datos"]) for p in db.consultar("SELECT datos FROM perfiles")])

@app.route("/api/cultivos")
def cultivos():
    return jsonify(db.consultar("SELECT * FROM cultivos"))

@app.route("/api/estado")
def estado():
    n = lambda t: db.consultar(f"SELECT COUNT(*) n FROM {t} WHERE verificado=0")[0]["n"]
    return jsonify({t: n(t) for t in ("cultivos", "zonas", "clima", "perfiles")})

@app.route("/api/clima_diario")
def clima_diario():
    return jsonify(motor.diario(request.args["zona_id"], int(request.args["mes"]), int(request.args.get("anio", date.today().year))))

@app.route("/api/panel", methods=["POST"])
def panel():
    d = request.get_json(force=True)
    return jsonify(motor.panel(d["zona_id"], _suelo(d["suelo"]), d.get("textura"), d.get("riego")))

@app.route("/api/recomendar", methods=["POST"])
def recomendar():
    d = request.get_json(force=True)
    return jsonify(motor.recomendar(d["zona_id"], _suelo(d["suelo"]), d.get("prioridades"),
                                    d.get("ultimo_cultivo") or None, d.get("riego"), d.get("textura")))

@app.route("/api/simular", methods=["POST"])
def simular():
    d = request.get_json(force=True)
    return jsonify(motor.simular(d["zona_id"], _suelo(d["suelo"]), d.get("textura"), d.get("riego"), d["secuencia"],
                                 d.get("ultimo_cultivo") or None, max(.1, float(d.get("ha", 5))), max(1, min(10, int(d.get("anios", 5))))))

if __name__ == "__main__":
    app.run(debug=True)
