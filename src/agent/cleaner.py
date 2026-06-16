"""Filtro de contexto: seleciona skills relevantes para o prompt do usuário."""
import re

# Palavras-chave por domínio — mapeiam termos do usuário para skills relevantes
_DOMAIN_MAP = {
    "web_fetch":    ["fetch", "url", "http", "download", "página", "site", "curl"],
    "web_search":   ["search", "busca", "pesquisa", "google", "duckduckgo", "encontre"],
    "execute_shell":["run", "execute", "shell", "bash", "comando", "script", "rode"],
    "write_file":   ["write", "create", "crie", "escreva", "arquivo", "salve", "gere"],
    "read_file":    ["read", "leia", "abra", "veja", "conteúdo", "show", "cat"],
    "list_dir":     ["list", "liste", "diretório", "pasta", "files", "ls"],
    "grep":         ["grep", "busque", "encontre", "pattern", "regex", "ocorrência"],
    "glob":         ["glob", "extensão", "*.py", "arquivos", "pattern"],
    "validate_code":["valide", "validate", "syntax", "linting", "check", "código"],
    "git":          ["git", "commit", "diff", "status", "branch", "log"],
    "memory_set":   ["lembre", "salve", "guarde", "memorize", "armazene"],
    "memory_get":   ["lembre", "recupere", "recall", "memória", "o que sei"],
    "todo_write":   ["todo", "tarefa", "plano", "passo", "step", "task"],
    "analyze_dependency_graph": ["grafo", "dependência", "graph", "análise"],
    "get_patient":  ["paciente", "patient", "registro", "record"],
    "list_patients":["pacientes", "patients", "lista", "todos"],
}

def select(prompt: str, catalog: dict, max_skills: int = 6) -> list:
    """Retorna as skills mais relevantes para o prompt dado."""
    prompt_lower = prompt.lower()
    words = set(re.findall(r'\w+', prompt_lower))
    scores = {}
    for name in catalog:
        score = 0
        keywords = _DOMAIN_MAP.get(name, [])
        for kw in keywords:
            if kw in prompt_lower:
                score += 2
        # match parcial por palavras
        desc = catalog[name].get("description", "").lower()
        for w in words:
            if len(w) > 3 and w in desc:
                score += 1
        if score > 0:
            scores[name] = score
    # sempre inclui final_answer implicitamente
    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)[:max_skills]
    # se nenhuma skill for selecionada, retorna todas (fallback)
    if not ranked:
        ranked = list(catalog.keys())[:max_skills]
    return [catalog[n] for n in ranked]

def format_for_llm(skills: list) -> str:
    lines = []
    for s in skills:
        params = ", ".join(s.get("params", [])) or "none"
        lines.append(f"- {s['name']}({params}): {s['description']}")
    return "\n".join(lines)
