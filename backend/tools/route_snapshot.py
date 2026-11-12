"""
tools/route_snapshot.py — static refactor safety net (needs no dependencies).

Usage (from the repo root):
    python tools/route_snapshot.py --out before.txt  # on the code before a change
    python tools/route_snapshot.py --out after.txt   # after the change
    fc before.txt after.txt                          # Windows (or: diff before.txt after.txt)

    python tools/route_snapshot.py --check-names     # flag names a module uses but never defines/imports
    python tools/route_snapshot.py --check-imports   # flag core/features imports that point at nothing

What it records, independent of WHICH FILE things live in:
  ROUTE  <METHODS> <full url> -> <function> @<decorators>
  FUNC   <name> <hash of the function's code>    (every top-level function)
  CONST  <name> <hash of the assigned value>     (top-level constants such as role lists)

A pure "move code to another file" refactor must leave this output identical.
Intentional behavior changes show up as individual changed lines.

Only the blueprints that are being refactored are covered by default
(sheets.py plus any new modules); inventory.py / products.py define their own,
different copies of the auth decorators, so they are skipped. Pass --all to include them.
"""
import ast
import builtins
import hashlib
import re
import sys
from pathlib import Path

def _find_root():
    # Walk upward from this script until we find the folder holding app.py and blueprints/,
    # so it works whether tools/ sits in the project root or (by mistake) inside frontend/.
    for d in Path(__file__).resolve().parents:
        if (d / 'app.py').exists() and ((d / 'features').is_dir() or (d / 'blueprints').is_dir()):
            return d
    raise SystemExit('Could not find app.py + features/ (or blueprints/) above ' + str(Path(__file__).resolve()))


ROOT = _find_root()
BP_DIR = ROOT / 'blueprints'
NEW_LAYOUT = (ROOT / 'features').is_dir()
SKIP_BY_DEFAULT = {'inventory.py', 'products.py', '__init__.py'}


def digest(node):
    return hashlib.sha1(ast.dump(node, include_attributes=False).encode()).hexdigest()[:10]


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except Exception:
        return default


def blueprint_prefixes():
    """Map module name -> effective url_prefix, from each module's Blueprint(...) and app.py's registration."""
    registered = {}
    imports = {}  # alias -> module
    for line in (ROOT / 'app.py').read_text(encoding='utf-8').splitlines():  # old layout only; harmless otherwise
        s = line.strip()
        if s.startswith('#'):
            continue
        m = re.match(r'from blueprints\.(\w+) import bp as (\w+)', s)
        if m:
            imports[m.group(2)] = m.group(1)
        for alias, args in re.findall(r'register_blueprint\((\w+)([^)]*)\)', s):
            p = re.search(r"url_prefix\s*=\s*['\"]([^'\"]*)['\"]", args)
            registered[alias] = p.group(1) if p else None
    result = {}
    for alias, module in imports.items():
        if alias in registered:
            result[module] = registered[alias]
    return result


def bp_default_prefix(tree):
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'Blueprint'):
            for kw in n.keywords:
                if kw.arg == 'url_prefix':
                    return literal(kw.value, '')
    return ''


def decorator_name(d):
    if isinstance(d, ast.Call):
        return decorator_name(d.func)
    if isinstance(d, ast.Attribute):
        return d.attr
    return getattr(d, 'id', '?')


def modules(include_all):
    if NEW_LAYOUT:
        # backend/features/**/*.py and backend/core/*.py (everything is covered; __init__ files are skipped)
        for sub in ('core', 'features'):
            for p in sorted((ROOT / sub).rglob('*.py')):
                if p.name != '__init__.py':
                    yield p
        return
    for p in sorted(BP_DIR.glob('*.py')):
        if include_all or p.name not in SKIP_BY_DEFAULT:
            yield p


def snapshot(include_all):
    prefixes = blueprint_prefixes()
    lines = []
    for path in modules(include_all):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        module = path.stem
        # new layout: module names are unique per file, same lookup works
        prefix = prefixes.get(module)
        if prefix is None:
            prefix = bp_default_prefix(tree)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                lines.append(f'FUNC  {node.name} {digest(node)}')
                routes, others = [], []
                for d in node.decorator_list:
                    if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                            and d.func.attr == 'route'):
                        rule = literal(d.args[0], '?')
                        methods = ['GET']
                        for kw in d.keywords:
                            if kw.arg == 'methods':
                                methods = literal(kw.value, ['?'])
                        routes.append((rule, sorted(methods)))
                    else:
                        others.append(decorator_name(d))
                for rule, methods in routes:
                    lines.append(f"ROUTE {','.join(methods):<14} {prefix}{rule} -> {node.name} @{','.join(others)}")
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id.isupper():
                        lines.append(f'CONST {t.id} {digest(node.value)}')
    return sorted(set(lines))


def bound_names(tree):
    names = set(dir(builtins)) | {'__name__', '__file__'}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        if isinstance(n, ast.arg):
            names.add(n.arg)
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        if isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split('.')[0])
    return names


def check_names(include_all):
    problems = 0
    for path in modules(include_all):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        bound = bound_names(tree)
        seen = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in bound:
                seen.setdefault(n.id, n.lineno)
        for name, line in sorted(seen.items()):
            print(f'{path.name}:{line}: name {name!r} is used but never defined or imported')
            problems += 1
    if not problems:
        print('check-names: OK (no undefined names found)')
    return problems


def top_level_names(tree):
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        names.add(x.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split('.')[0])
    return names


def check_imports():
    """Every `from core...` / `from features...` import must point at a real module and a real top-level name."""
    problems = 0
    files = [ROOT / 'app.py'] + [p for sub in ('core', 'features') for p in sorted((ROOT / sub).rglob('*.py'))]
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if not isinstance(n, ast.ImportFrom) or not n.module:
                continue
            if n.module.split('.')[0] not in ('core', 'features'):
                continue
            target = ROOT.joinpath(*n.module.split('.'))
            mod_file = target.with_suffix('.py')
            pkg_init = target / '__init__.py'
            if mod_file.exists():
                defined = top_level_names(ast.parse(mod_file.read_text(encoding='utf-8')))
            elif pkg_init.exists():
                defined = top_level_names(ast.parse(pkg_init.read_text(encoding='utf-8')))
                # `from package import submodule` is also fine
                defined |= {p.stem for p in target.glob('*.py')} | {p.name for p in target.iterdir() if p.is_dir()}
            else:
                print(f'{path.relative_to(ROOT)}:{n.lineno}: module {n.module!r} not found')
                problems += 1
                continue
            for a in n.names:
                if a.name != '*' and a.name not in defined:
                    print(f'{path.relative_to(ROOT)}:{n.lineno}: {n.module} has no name {a.name!r}')
                    problems += 1
    # every package folder needs an __init__.py
    for sub in ('core', 'features'):
        for d in [ROOT / sub] + [x for x in (ROOT / sub).rglob('*') if x.is_dir() and x.name != '__pycache__']:
            if not (d / '__init__.py').exists():
                print(f'{d.relative_to(ROOT)}: missing __init__.py')
                problems += 1
    if not problems:
        print('check-imports: OK (every core/features import resolves)')
    return problems


if __name__ == '__main__':
    inc = '--all' in sys.argv
    if '--check-names' in sys.argv:
        sys.exit(1 if check_names(inc) else 0)
    if '--check-imports' in sys.argv:
        sys.exit(1 if check_imports() else 0)
    out = '\n'.join(snapshot(inc)) + '\n'
    if '--out' in sys.argv:
        # Write UTF-8 with plain newlines (PowerShell's ">" would write UTF-16, which breaks comparisons).
        with open(sys.argv[sys.argv.index('--out') + 1], 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)
