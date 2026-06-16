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

def _analyze_dependency_graph(params):
    import ast as _ast

    # Nós: todas as skills do catálogo
    nodes = list(_catalog.keys())

    # Arestas: parse do main.py buscando quais funções _INTERNAL chamam subprocess/urlopen
    edges = []
    src_path = os.path.join(os.path.dirname(__file__), "main.py")
    try:
        with open(src_path) as f:
            tree = _ast.parse(f.read())
        # Mapeia cada função interna para as calls que ela faz
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name.startswith("_"):
                skill_name = node.name.lstrip("_")
                if skill_name in _catalog:
                    for child in _ast.walk(node):
                        if isinstance(child, _ast.Call):
                            if isinstance(child.func, _ast.Attribute):
                                edges.append({"from": skill_name, "calls": child.func.attr})
    except Exception as e:
        edges = [{"error": str(e)}]

    # Arestas de segurança: regras do catálogo (upstream)
    policy = []
    for name, skill in _catalog.items():
        policy.append({
            "skill": name,
            "upstream": skill["upstream"],
            "requires_delegation": True
        })

    try:
        import networkx as nx
        G = nx.DiGraph()
        G.add_nodes_from(nodes)
        for e in edges:
            if "from" in e and "calls" in e:
                G.add_edge(e["from"], e["calls"])
        cycles = list(nx.simple_cycles(G))
        return 200, {"nodes": list(G.nodes), "edges": list(G.edges), "cycles": cycles, "policy": policy}
    except ImportError:
        return 200, {"nodes": nodes, "edges": edges, "policy": policy, "note": "networkx not installed — install for cycle detection"}

_INTERNAL["analyze_dependency_graph"] = _analyze_dependency_graph

def _web_fetch(params):
    url = params.get("url", "")
    if not url:
        return 400, {"error": "url required"}
    try:
        import html.parser
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode(errors="replace")
        # strip tags para retornar texto legível
        class _S(html.parser.HTMLParser):
            def __init__(self): super().__init__(); self.parts = []; self._skip = False
            def handle_starttag(self, t, a): self._skip = t in ("script","style")
            def handle_endtag(self, t): self._skip = False
            def handle_data(self, d):
                if not self._skip and d.strip(): self.parts.append(d.strip())
        p = _S(); p.feed(raw)
        text = "\n".join(p.parts)[:8000]
        return 200, {"url": url, "text": text}
    except Exception as e:
        return 500, {"error": str(e)}

def _web_search(params):
    query = params.get("query", "")
    if not query:
        return 400, {"error": "query required"}
    try:
        import html.parser, urllib.parse, re
        url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode(errors="replace")
        results = []
        # extrai pares link + snippet da tabela do lite
        links    = re.findall(r'uddg=([^&"]+)', raw)
        titles   = re.findall(r"class='result-link'>(.*?)</a>", raw)
        snippets = re.findall(r"class='result-snippet'>(.*?)</span>", raw, re.S)
        for i in range(min(5, len(titles))):
            results.append({
                "url":     urllib.parse.unquote(links[i]) if i < len(links) else "",
                "title":   re.sub(r"<[^>]+>", "", titles[i]).strip(),
                "snippet": re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
            })
        return 200, {"query": query, "results": results}
    except Exception as e:
        return 500, {"error": str(e)}

_INTERNAL["web_fetch"]  = _web_fetch
_INTERNAL["web_search"] = _web_search

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
