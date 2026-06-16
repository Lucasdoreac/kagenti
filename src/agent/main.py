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
# CWD persistente entre chamadas de execute_shell
_CWD = [WORKSPACE]

def _exec_shell(params):
    cmd     = params.get("command", "")
    timeout = int(params.get("timeout", 30))
    if not cmd:
        return 400, {"error": "command required"}
    # suporte a cd — atualiza CWD sem spawnar novo shell
    stripped = cmd.strip()
    if stripped.startswith("cd "):
        target = stripped[3:].strip()
        new_cwd = target if os.path.isabs(target) else os.path.normpath(os.path.join(_CWD[0], target))
        if os.path.isdir(new_cwd):
            _CWD[0] = new_cwd
            return 200, {"stdout": "", "stderr": "", "code": 0, "cwd": _CWD[0]}
        return 200, {"stdout": "", "stderr": f"cd: {target}: No such directory", "code": 1}
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                             cwd=_CWD[0], timeout=timeout)
        LIMIT = 8000
        stdout = res.stdout
        stderr = res.stderr
        truncated = False
        if len(stdout) > LIMIT:
            stdout = stdout[:3000] + f"\n...[truncated {len(stdout)-LIMIT} chars]...\n" + stdout[-1000:]
            truncated = True
        return 200, {"stdout": stdout, "stderr": stderr[:2000], "code": res.returncode,
                     "cwd": _CWD[0], "truncated": truncated}
    except subprocess.TimeoutExpired:
        return 200, {"stdout": "", "stderr": f"timeout after {timeout}s", "code": -1, "cwd": _CWD[0]}

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

def _fs_edit(params):
    file_path  = params.get("file_path", "")
    old_string = params.get("old_string", "")
    new_string = params.get("new_string", "")
    if not file_path or old_string == "":
        return 400, {"error": "file_path and old_string required"}
    full = file_path if os.path.isabs(file_path) else os.path.join(_CWD[0], file_path)
    safe = os.path.normpath(full)
    try:
        with open(safe, "r", errors="replace") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return 422, {"error": "old_string not found — read the file first and verify exact whitespace/indentation"}
        if count > 1:
            return 422, {"error": f"old_string matches {count} locations — expand context to make it unique"}
        new_content = content.replace(old_string, new_string, 1)
        with open(safe, "w") as f:
            f.write(new_content)
        return 200, {"status": "ok", "path": safe, "replacements": 1}
    except Exception as e:
        return 500, {"error": str(e)}

_INTERNAL = {"execute_shell": _exec_shell, "write_file": _write_file, "fs_edit": _fs_edit}

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

def _read_file(params):
    path   = params.get("path", "")
    offset = int(params.get("offset", 0))   # linha inicial (0-indexed)
    limit  = int(params.get("limit", 200))  # max linhas
    if not path: return 400, {"error": "path required"}
    full = path if os.path.isabs(path) else os.path.join(_CWD[0], path)
    safe = os.path.normpath(full)
    try:
        with open(safe, errors="replace") as f:
            lines = f.readlines()
        total   = len(lines)
        chunk   = lines[offset: offset + limit]
        numbered = "".join(f"{offset+i+1:4d} | {l}" for i, l in enumerate(chunk))
        partial = (offset + limit) < total
        result  = {"path": safe, "content": numbered, "total_lines": total,
                   "offset": offset, "limit": limit}
        if partial:
            result["warning"] = f"PARTIAL view — {total-(offset+limit)} lines remaining, use offset={offset+limit}"
        return 200, result
    except Exception as e: return 500, {"error": str(e)}

def _list_dir(params):
    path = params.get("path", WORKSPACE)
    full = path if os.path.isabs(path) else os.path.join(WORKSPACE, path)
    try:
        entries = []
        for e in os.scandir(full):
            entries.append({"name": e.name, "type": "dir" if e.is_dir() else "file",
                            "size": e.stat().st_size if e.is_file() else None})
        return 200, {"path": full, "entries": entries}
    except Exception as e: return 500, {"error": str(e)}

def _grep(params):
    pattern = params.get("pattern", "")
    path    = params.get("path", WORKSPACE)
    if not pattern: return 400, {"error": "pattern required"}
    full = path if os.path.isabs(path) else os.path.join(WORKSPACE, path)
    import re
    matches = []
    for root, _, files in os.walk(full):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(pattern, line):
                            matches.append({"file": fpath, "line": i, "text": line.rstrip()})
                            if len(matches) >= 50: break
            except: pass
        if len(matches) >= 50: break
    return 200, {"pattern": pattern, "matches": matches}

def _glob(params):
    import glob as _glob
    pattern = params.get("pattern", "")
    if not pattern: return 400, {"error": "pattern required"}
    full_pattern = os.path.join(WORKSPACE, pattern)
    files = _glob.glob(full_pattern, recursive=True)
    return 200, {"pattern": pattern, "files": files[:100]}

def _git(params):
    cmd = params.get("command", "")
    if not cmd: return 400, {"error": "command required"}
    # bloqueia operações destrutivas
    blocked = ["push", "reset --hard", "clean -f", "branch -D"]
    if any(b in cmd for b in blocked):
        return 403, {"error": f"blocked: use execute_shell with explicit confirmation"}
    try:
        res = subprocess.run(f"git {cmd}", shell=True, capture_output=True,
                             text=True, cwd=WORKSPACE, timeout=15)
        return 200, {"stdout": res.stdout, "stderr": res.stderr, "code": res.returncode}
    except Exception as e: return 500, {"error": str(e)}

for _name, _fn in [("read_file",_read_file),("list_dir",_list_dir),
                   ("grep",_grep),("glob",_glob),("git",_git)]:
    _INTERNAL[_name] = _fn

# --- memory e todo (estado em memória do processo) ---
_MEMORY: dict = {}
_TODOS:  list = []

def _memory_set(params):
    k, v = params.get("key",""), params.get("value","")
    if not k: return 400, {"error": "key required"}
    _MEMORY[k] = v
    return 200, {"stored": k}

def _memory_get(params):
    k = params.get("key","")
    if k == "*": return 200, {"memory": _MEMORY}
    if k not in _MEMORY: return 404, {"error": f"key '{k}' not found"}
    return 200, {"key": k, "value": _MEMORY[k]}

def _todo_write(params):
    action = params.get("action", "list")
    task   = params.get("task", "")
    if action == "add":
        if not task: return 400, {"error": "task required"}
        _TODOS.append({"task": task, "done": False})
        return 200, {"todos": _TODOS}
    if action == "complete":
        for t in _TODOS:
            if t["task"] == task: t["done"] = True
        return 200, {"todos": _TODOS}
    if action == "clear":
        _TODOS.clear()
        return 200, {"todos": []}
    return 200, {"todos": _TODOS}  # list

for _n, _f in [("memory_set",_memory_set),("memory_get",_memory_get),("todo_write",_todo_write)]:
    _INTERNAL[_n] = _f

def _get_context(params):
    # 1. CONTEXT.md do repo (montado junto com main.py se disponível)
    for candidate in [
        os.path.join(os.path.dirname(__file__), "..", "CONTEXT.md"),
        "/context/CONTEXT.md",
        os.path.join(WORKSPACE, "CONTEXT.md"),
    ]:
        path = os.path.normpath(candidate)
        if os.path.exists(path):
            with open(path) as f:
                return 200, {"source": path, "content": f.read()}
    # 2. fallback: constrói resumo dinâmico do estado atual
    summary = {
        "project": "kagenti — skill execution harness with Envoy OBridge sidecar",
        "repo": "https://github.com/Lucasdoreac/kagenti",
        "endpoints": ["/healthz", "/skills", "/mcp", "/run", "/chat"],
        "skills": list(_catalog.keys()),
        "memory_keys": list(_MEMORY.keys()),
        "todos": _TODOS,
        "ollama": {"host": os.environ.get("OLLAMA_HOST","http://host.docker.internal:11434"), "needed_for": "/chat"},
        "next_steps": [
            "start ollama + pull gemma3:12b to enable /chat",
            "rename project (conflicts with Red Hat kagenti)",
            "create ludoc brand via ferdinandobons/brand-docs",
        ]
    }
    return 200, summary

_INTERNAL["get_context"] = _get_context

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
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}
        caller = self.headers.get("X-Delegation-Chain", "unknown")
        if caller == "unknown":
            return self.send_json(403, {"error": "missing X-Delegation-Chain — requests must pass through OBridge"})

        # --- /run: execução direta de skill ---
        if self.path == "/run":
            skill_name = body.get("skill")
            params     = body.get("params", {})
            if not skill_name:
                return self.send_json(400, {"error": "skill required"})
            code, result = run_skill(skill_name, params, caller)
            return self.send_json(code, {"caller": caller, "skill": skill_name, "result": result})

        # --- /chat: loop ReAct via Ollama ---
        if self.path == "/chat":
            import sys, os as _os
            sys.path.insert(0, _os.path.dirname(__file__))
            try:
                import llm, cleaner
            except ImportError as e:
                return self.send_json(503, {"error": f"llm/cleaner not available: {e}"})

            if not llm.available():
                return self.send_json(503, {"error": "Ollama unreachable", "hint": f"start ollama at {llm.OLLAMA_HOST}"})

            prompt   = body.get("prompt", "")
            model    = body.get("model", llm.DEFAULT_MODEL)
            max_iter = int(body.get("max_iter", 10))
            if not prompt:
                return self.send_json(400, {"error": "prompt required"})

            relevant  = cleaner.select(prompt, _catalog)
            tools_ctx = cleaner.format_for_llm(relevant)
            messages  = [{"role": "user", "content": prompt}]
            trace     = []

            for i in range(max_iter):
                decision = llm.call(llm.trim_history(messages), model=model, tools_context=tools_ctx)
                trace.append({"iter": i+1, "decision": decision})

                action = decision.get("action", "final_answer")
                params = decision.get("params", {})

                if action == "final_answer":
                    return self.send_json(200, {
                        "caller": caller, "answer": params.get("text",""),
                        "iterations": i+1, "trace": trace
                    })

                code, result = run_skill(action, params, caller)
                obs = {"skill": action, "result": result}
                messages.append({"role": "assistant", "content": json.dumps(decision)})
                messages.append({"role": "user",      "content": f"Observation: {json.dumps(obs)}"})

            return self.send_json(200, {"caller": caller, "answer": "max iterations reached",
                                        "iterations": max_iter, "trace": trace})

        self.send_json(404, {"error": "not found"})

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", 8080), Handler)
    print(f"agent listening on :8080, skills loaded: {list(_catalog)}", flush=True)
    server.serve_forever()
