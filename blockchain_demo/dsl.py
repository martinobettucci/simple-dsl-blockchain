import re
from typing import Dict

TOKEN_RE = re.compile(r"let\s+(\w+)\s*=\s*([\w+-]+)")

class DSLExecutionError(Exception):
    pass


def parse_script(script: str):
    statements = []
    for stmt in script.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = TOKEN_RE.fullmatch(stmt)
        if not m:
            raise DSLExecutionError(f"Invalid statement: {stmt}")
        var, expr = m.groups()
        statements.append((var, expr))
    return statements


def execute(script: str, state: Dict[str, int]) -> Dict[str, int]:
    state = state.copy()
    for var, expr in parse_script(script):
        try:
            value = eval(expr, {}, state)
        except Exception as e:
            raise DSLExecutionError(str(e))
        state[var] = value
    return state
