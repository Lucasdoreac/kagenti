import json, urllib.request, urllib.error, http.server, subprocess, os

PROXY      = "http://localhost:15001"
WORKSPACE  = "/tmp/workspace"
os.makedirs(WORKSPACE, exist_ok=True)
SKILLS_FILE = os.path.join(os.path.dirname(__file__), "skills.json")

# --- carrega catálogo de skills ---
with open(SKILLS_FILE) as f:
    _catalog = {s["name"]: s for s in json.load(f)}

def list_skills():
    return [{"name": s["name"], "description": s["description"], "params": s["params"]}
            for s in _catalog.values()]

# --- handlers locais (internal_exec) ---
def _exec_shell(params):
    cmd = params.get("command", "")
    if not cmd:
        return 400, {"error": "command required"}
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=WORKSPACE, timeout=30)
    return 200, {"stdout": res.stdout, "stderr": res.stderr, "code": res.returncode}

def _write_file(params):
    filename = params.get("filename", "")
    content  = params.get("content", "")
    if not filename:
        return 400, {"error": "filename required"}
    safe = os.path.normpath(os.path.join(WORKSPACE, filename))
    if not safe.startswith(WORKSPACE):
        return 403, {"error": "path traversal denied"}
    parent = os.path.dirname(safe)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(safe, "w") as f:
        f.write(content)
    return 200, {"status": "ok", "path": safe}

_INTERNAL = {"execute_shell": _exec_shell, "write_file": _write_file}

def _validate_code(params):
    code = params.get("code", "")
    if not code:
        return 400, {"error": "code required"}
    try:
        import ast
        ast.parse(code)
    except SyntaxError as e:
        return 200, {"valid": False, "error": f"SyntaxError: {e}"}
    # ruff se disponível
    tmp = os.path.join(WORKSPACE, "_validate_tmp.py")
    with open(tmp, "w") as f:
        f.write(code)
    try:
        res = subprocess.run(["ruff", "check", "--select=E,F", tmp],
                             capture_output=True, text=True)
        os.unlink(tmp)
        if res.returncode != 0:
            return 200, {"valid": False, "error": res.stdout.strip()}
    except FileNotFoundError:
        os.unlink(tmp)  # ruff não instalado — ast.parse já passou, aceita
    return 200, {"valid": True}

_INTERNAL["validate_code"] = _validate_code

# --- executor genérico de skill ---
def run_skill(name, params, caller=None):
    skill = _catalog.get(name)
    if not skill:
        return 404, {"error": f"skill '{name}' not found"}
    if skill["upstream"] == "internal_exec":
        return _INTERNAL[name](params)
    path = skill["upstream"]
    for k, v in params.items():
        path = path.replace(f"{{{k}}}", str(v))
    try:
        with urllib.request.urlopen(f"{PROXY}{path}", timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": str(e.reason)}

# --- servidor HTTP ---
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.send_json(200, {"status": "ok"})
        if self.path == "/skills":
            return self.send_json(200, list_skills())
        if self.path == "/mcp":
            tools = [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "inputSchema": {
                        "type": "object",
                        "properties": {p: {"type": "string"} for p in s["params"]},
                        "required": s["params"]
                    },
                    "systemInstruction": s.get("system_instruction", "")
                }
                for s in _catalog.values()
            ]
            return self.send_json(200, {"schema": "mcp-tools/v1", "tools": tools})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self.send_json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        skill_name = body.get("skill")
        params     = body.get("params", {})
        caller     = self.headers.get("X-Delegation-Chain", "unknown")
        if caller == "unknown":
            return self.send_json(403, {"error": "missing X-Delegation-Chain — requests must pass through OBridge"})
        if not skill_name:
            return self.send_json(400, {"error": "skill required"})
        code, result = run_skill(skill_name, params, caller)
        self.send_json(code, {"caller": caller, "skill": skill_name, "result": result})

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 8080), Handler)
    print(f"agent listening on :8080, skills loaded: {list(_catalog)}", flush=True)
    server.serve_forever()
