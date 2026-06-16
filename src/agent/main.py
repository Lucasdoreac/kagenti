import json, urllib.request, urllib.error, http.server

PROXY = "http://localhost:15001"

def fetch(path):
    try:
        with urllib.request.urlopen(f"{PROXY}{path}", timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}

def triage(patient):
    c = patient.get("condition")
    n = patient.get("name", "?")
    if c == "critical":   return {"level": "ALERTA", "msg": f"{n} em estado crítico. Acionar equipe médica."}
    if c == "discharged": return {"level": "INFO",   "msg": f"{n} já teve alta."}
    return                       {"level": "OK",     "msg": f"{n} estável."}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/triage":
            return self.send_json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        pid = str(body.get("patient_id", ""))
        if not pid:
            return self.send_json(400, {"error": "patient_id required"})
        status, patient = fetch(f"/patients/{pid}")
        if status != 200:
            return self.send_json(status, {"error": "patient not found"})
        self.send_json(200, triage(patient))

    def do_GET(self):
        if self.path == "/healthz":
            return self.send_json(200, {"status": "ok"})
        self.send_json(404, {"error": "not found"})

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 8080), Handler)
    print("agent listening on :8080", flush=True)
    server.serve_forever()
