"""Code Translation Agent: JavaScript -> Python, keeping variable names.

No API key and no extra packages needed. Python 3.8+ only.

Usage:  python agent.py path/to/input.js [-o output.py] [--retries 3]

Agent loop:  read file -> extract names -> translate (rules) -> verify (ast + names)
             -> if the check fails, repair using the error -> verify again.
"""
import argparse
import ast
import keyword
import re
import sys

# ---------------------------------------------------------------- tools
def read_file(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


TOKEN = re.compile(
    r"//[^\n]*|/\*.*?\*/"
    r"|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`",
    re.S,
)


def protect(js):
    """Hide strings and comments behind placeholders so rules never touch them."""
    strs, cmts = [], []

    def keep(m):
        t = m.group(0)
        if t.startswith("//") or t.startswith("/*"):
            text = t[2:] if t.startswith("//") else t[2:-2]
            cmts.append("# " + " ".join(text.split()))
            return "\x01%d\x01" % (len(cmts) - 1)
        if t[0] == "`":
            parts = re.split(r"\$\{(.*?)\}", t[1:-1])
            f = ""
            for i, p in enumerate(parts):
                if i % 2:
                    f += "{" + expr(p).replace('"', "'") + "}"
                else:
                    f += p.replace("{", "{{").replace("}", "}}").replace('"', '\\"')
            strs.append('f"' + f + '"')
        else:
            strs.append(t)
        return "\x00%d\x00" % (len(strs) - 1)

    return TOKEN.sub(keep, js), strs, cmts


def extract_names(js):
    """Every variable, function, class and parameter name declared in the JS."""
    code, _, _ = protect(js)
    names = set()
    names.update(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_]\w*)", code))
    names.update(re.findall(r"\b(?:function|class)\s+([A-Za-z_]\w*)", code))
    plist = re.findall(r"\bfunction\s*\w*\s*\(([^)]*)\)", code)
    plist += re.findall(r"\(([^()]*)\)\s*=>", code)
    for m in re.finditer(r"^\s*(?:static\s+)?([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{", code, re.M):
        if m.group(1) in ("if", "for", "while", "switch", "catch", "function"):
            continue
        if m.group(1) != "constructor":
            names.add(m.group(1))  # class method name
        plist.append(m.group(2))
    for params in plist:
        for p in params.split(","):
            q = re.match(r"\s*(?:\.\.\.)?([A-Za-z_]\w*)", p)
            if q:
                names.add(q.group(1))
    names.update(re.findall(r"\b([A-Za-z_]\w*)\s*=>", code))
    names.update(re.findall(r"\bfor\s*\(\s*(?:const|let|var)\s+([A-Za-z_]\w*)", code))
    return names


# ---------------------------------------------------------------- translate
MATH = {"floor": "math.floor", "ceil": "math.ceil", "sqrt": "math.sqrt", "pow": "math.pow",
        "PI": "math.pi", "max": "max", "min": "min", "abs": "abs", "round": "round",
        "random": "random.random"}
METHODS = {"push": "append", "toUpperCase": "upper", "toLowerCase": "lower", "trim": "strip"}
NO_SUBSCRIPT = {"self", "math", "random"}
USED = set()


def expr(s, literal=False):
    s = re.sub(r"\bnew\s+(?=[A-Z])", "", s)
    s = s.replace("===", "==").replace("!==", "!=").replace("&&", " and ").replace("||", " or ")
    s = re.sub(r"!(?!=)", " not ", s)
    for js, py in (("true", "True"), ("false", "False"), ("null", "None"), ("undefined", "None"),
                   ("this", "self")):
        s = re.sub(r"\b%s\b" % js, py, s)
    s = s.replace("console.log(", "print(")

    def math_fn(m):
        USED.add("math" if MATH[m.group(1)].startswith("math") else "random" if "random" in MATH[m.group(1)] else "")
        return MATH[m.group(1)]
    s = re.sub(r"\bMath\.(\w+)", lambda m: math_fn(m) if m.group(1) in MATH else m.group(0), s)
    for js, py in METHODS.items():
        s = re.sub(r"\.%s\(" % js, ".%s(" % py, s)
    s = re.sub(r"([A-Za-z_]\w*(?:\.[A-Za-z_]\w*|\[[^\]]*\])*)\.length\b", r"len(\1)", s)

    def sub(m):
        base, props, call = m.group(1), m.group(2).split(".")[1:], m.group(3)
        if base in NO_SUBSCRIPT:
            return m.group(0)
        keep = [props.pop()] if call else []
        out = base + "".join('["%s"]' % p for p in props)
        return out + ("." + keep[0] + call if keep else "")
    s = re.sub(r"(?<![\w.\]\)\"])([A-Za-z_]\w*)((?:\.[A-Za-z_]\w*)+)(\s*\()?", sub, s)

    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(\])\.([A-Za-z_]\w*)(?![\w(])", r'\1["\2"]', s)

    if literal or "{" in s:
        s = re.sub(r"(^\s*|[{,]\s*)([A-Za-z_]\w*)\s*:(?!:)", r'\1"\2":', s) if literal else \
            re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:(?!:)", r'\1"\2":', s)
    if "?" in s:
        m = re.match(r"^((?:return|[\w.\[\]\"]+\s*[+\-*/]?=(?!=))\s*)?(.+?)\s*\?\s*(.+?)\s*:\s*(.+)$", s)
        if m:
            s = "%s%s if %s else %s" % (m.group(1) or "", m.group(3), m.group(2), m.group(4))
    return re.sub(r"\s+", " ", s).strip() if "\x00" not in s else s.strip()


def params(p):
    return re.sub(r"\.\.\.(\w+)", r"*\1", p).strip()


def for_header(h):
    m = re.match(r"for\s*\((?:const|let|var)?\s*(\w+)\s+(of|in)\s+(.+)\)$", h)
    if m:
        return "for %s in %s:" % (m.group(1), expr(m.group(3)))
    m = re.match(r"for\s*\((?:let|const|var)?\s*(\w+)\s*=\s*(.+?);\s*\1\s*(<=|<|>=|>)\s*(.+?);\s*(.+)\)$", h)
    if not m:
        return None
    v, start, op, end, upd = m.groups()
    if re.fullmatch(r"%s\s*(\+\+|--)|(\+\+|--)\s*%s" % (v, v), upd):
        step = "1" if "+" in upd else "-1"
    else:
        u = re.fullmatch(r"%s\s*([+-])=\s*(\S+)" % v, upd)
        if not u:
            return None
        step = u.group(2) if u.group(1) == "+" else "-" + u.group(2)
    end, start = expr(end), expr(start)
    if op in ("<=", ">="):
        d = 1 if op == "<=" else -1
        end = str(int(end) + d) if end.lstrip("-").isdigit() else "%s %s 1" % (end, "+" if d > 0 else "-")
    args = [start, end] + ([] if step == "1" else [step])
    return "for %s in range(%s):" % (v, ", ".join(args))


def header(h, in_class):
    """Translate a block opener (text before '{'). Returns (python_header, kind) or None."""
    m = re.match(r"(?:async\s+)?function\s+(\w+)\s*\((.*)\)$", h)
    if m:
        return "def %s(%s):" % (m.group(1), params(m.group(2))), "block"
    m = re.match(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function\s*\((.*)\)|\((.*)\)\s*=>|(\w+)\s*=>)$", h)
    if m:
        return "def %s(%s):" % (m.group(1), params(m.group(2) or m.group(3) or m.group(4) or "")), "block"
    m = re.match(r"class\s+(\w+)(?:\s+extends\s+(\w+))?$", h)
    if m:
        return "class %s%s:" % (m.group(1), "(%s)" % m.group(2) if m.group(2) else ""), "class"
    m = re.match(r"if\s*\((.*)\)$", h)
    if m:
        return "if %s:" % expr(m.group(1)), "block"
    m = re.match(r"else\s+if\s*\((.*)\)$", h)
    if m:
        return "elif %s:" % expr(m.group(1)), "block"
    if h == "else":
        return "else:", "block"
    m = re.match(r"while\s*\((.*)\)$", h)
    if m:
        return "while %s:" % expr(m.group(1)), "block"
    if h.startswith("for"):
        f = for_header(h)
        return (f, "block") if f else None
    if h == "try":
        return "try:", "block"
    if h == "finally":
        return "finally:", "block"
    m = re.match(r"catch\s*(?:\((\w+)\))?$", h)
    if m:
        return ("except Exception as %s:" % m.group(1) if m.group(1) else "except Exception:"), "block"
    if in_class:
        m = re.match(r"(?:static\s+)?(\w+)\s*\((.*)\)$", h)
        if m and m.group(1) not in ("if", "for", "while", "switch", "catch"):
            name = "__init__" if m.group(1) == "constructor" else m.group(1)
            p = params(m.group(2))
            return "def %s(%s):" % (name, "self, " + p if p else "self"), "block"
    return None


def statement(s):
    s = re.sub(r"^(?:const|let|var)\s+", "", s)
    m = re.fullmatch(r"(\S+?)\s*(\+\+|--)", s)
    if m:
        return "%s %s= 1" % (m.group(1), m.group(2)[0])
    m = re.match(r"throw\s+(.*)", s)
    if m:
        return "raise " + expr(m.group(1)).replace("Error(", "Exception(", 1)
    m = re.fullmatch(r"(\w+)\s*=\s*(?:\((.*?)\)|(\w+))\s*=>\s*([^{].*)", s)
    if m:
        return "%s = lambda %s: %s" % (m.group(1), params(m.group(2) or m.group(3) or ""), expr(m.group(4)))
    return expr(s)


def translate(js, names):
    USED.clear()
    code, strs, cmts = protect(js)
    for n in names:
        if keyword.iskeyword(n):
            code = re.sub(r"\b%s\b" % n, n + "_", code)
    out, stack, ind = [], [], 0
    for raw in code.split("\n"):
        s, cm = raw.strip(), ""
        m = re.search(r"\s*(\x01\d+\x01)\s*$", s)
        if m:
            cm, s = "  " + m.group(1), s[:m.start()].strip()
        s = s.rstrip(";").strip()
        pad = lambda: "    " * (ind + stack.count("literal"))
        if not s:
            out.append((pad() + cm.strip()) if cm else "")
            continue
        if s.startswith("}"):
            kind = stack.pop() if stack else "block"
            if kind == "literal":
                out.append(pad() + expr(s, True) + cm)
                continue
            ind = max(0, ind - 1)
            s = s[1:].strip().rstrip(";").strip()
            if not s:
                if cm:
                    out.append(pad() + cm.strip())
                continue
        em = re.match(r"(.*?)\s*\{\s*\}$", s)
        if em and header(em.group(1).strip(), False):
            out.append(pad() + header(em.group(1).strip(), False)[0] + cm)
            out.append(pad() + "    pass")
            continue
        if s.endswith("{"):
            h = header(s[:-1].strip(), bool(stack) and stack[-1] == "class")
            before = s[:-1].strip()
            if h:
                out.append(pad() + h[0] + cm)
                stack.append(h[1])
                ind += 1
            elif before == "" or re.search(r"(=|\(|,|:|\[|return|=>)$", before):
                out.append(pad() + statement(s) + cm)
                stack.append("literal")
            else:
                out.append(pad() + "if True:  # TODO could not translate: " + before)
                stack.append("block")
                ind += 1
            continue
        out.append(pad() + statement(s) if "literal" not in stack[-1:] else pad() + expr(s, True))
        out[-1] += cm
    py = "\n".join(out)
    py = re.sub(r"\x00(\d+)\x00", lambda m: strs[int(m.group(1))], py)
    py = re.sub(r"\x01(\d+)\x01", lambda m: cmts[int(m.group(1))], py)
    imports = "".join("import %s\n" % u for u in sorted(USED) if u)
    return (imports + "\n" if imports else "") + py.strip() + "\n"


# ---------------------------------------------------------------- verify + repair
def python_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def verify(py, js_names):
    """Return a list of problems. Empty list means the output passed."""
    try:
        tree = ast.parse(py)
    except SyntaxError as e:
        return ["Python syntax error on line %s: %s" % (e.lineno, e.msg)]
    found = python_names(tree)
    return ["Name '%s' is missing or was renamed." % (n + "_" if keyword.iskeyword(n) else n)
            for n in sorted(js_names)
            if (n + "_" if keyword.iskeyword(n) else n) not in found]


def repair(py):
    """Use the syntax error to fix the output: untranslatable lines become 'pass' + a TODO."""
    lines = py.split("\n")
    for _ in range(60):
        try:
            ast.parse("\n".join(lines))
            break
        except SyntaxError as e:
            i = min(max((e.lineno or 1) - 1, 0), len(lines) - 1)
            if "expected an indented block" in str(e.msg):
                prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
                ind = len(prev) - len(prev.lstrip()) + 4
            elif "unexpected indent" in str(e.msg) or "unindent" in str(e.msg):
                prev = next((l for l in reversed(lines[:i]) if l.strip()), "")
                ind = len(prev) - len(prev.lstrip())
            else:
                ind = len(lines[i]) - len(lines[i].lstrip())
            lines[i] = " " * ind + "pass  # TODO could not translate: " + lines[i].strip()
    return "\n".join(lines)


# ---------------------------------------------------------------- agent loop
def run(path, out_path, retries):
    js = read_file(path)
    names = extract_names(js)
    print("[1] Read %s (%d lines)" % (path, len(js.splitlines())))
    print("[2] Names to preserve: %s" % (", ".join(sorted(names)) or "(none)"))
    py = translate(js, names)
    print("[3] Translated using rules")
    problems = []
    for attempt in range(1, retries + 1):
        problems = verify(py, names)
        print("[4] Check %d: %s" % (attempt, "passed" if not problems else "%d problem(s)" % len(problems)))
        for p in problems:
            print("    -", p)
        if not problems or not any(p.startswith("Python syntax") for p in problems):
            break
        py = repair(py)
        print("[5] Repaired lines that could not be translated")
    try:
        ast.parse(py)
    except SyntaxError:
        print("Output still has syntax errors, not saved.")
        return 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(py)
    print("[6] Saved %s" % out_path)
    if "TODO could not translate" in py:
        print("    Some lines need manual work: search for 'TODO' in the output.")
    return 0 if not problems else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Translate a JavaScript file to Python, keeping names.")
    ap.add_argument("input", help="path to the .js file")
    ap.add_argument("-o", "--output", default="output.py")
    ap.add_argument("--retries", type=int, default=3)
    a = ap.parse_args()
    sys.exit(run(a.input, a.output, a.retries))
