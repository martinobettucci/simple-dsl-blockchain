import re
from typing import Dict, List, Tuple, Union

IDENT_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
INT_RE = re.compile(r"\d+")
TOKEN_RE = re.compile(r"\s*(?:(?P<int>\d+)|(?P<ident>[a-zA-Z_][a-zA-Z0-9_]*)|(?P<op>[+-]))")

class DSLExecutionError(Exception):
    pass


def _tokenize(expr: str) -> List[str]:
    tokens: List[str] = []
    pos = 0
    while pos < len(expr):
        m = TOKEN_RE.match(expr, pos)
        if not m:
            raise DSLExecutionError(f"Invalid syntax near: '{expr[pos:]}'")
        tokens.append(m.group(m.lastgroup))
        pos = m.end()
    return tokens


def _parse_expression(expr: str) -> List[Union[str, Tuple[str, str]]]:
    tokens = _tokenize(expr)
    if not tokens:
        raise DSLExecutionError("Empty expression")
    # Expect TERM (OP TERM)*
    ast: List[Union[str, Tuple[str, str]]] = []
    expect_term = True
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if expect_term:
            if INT_RE.fullmatch(tok) or IDENT_RE.fullmatch(tok):
                ast.append(tok)
                expect_term = False
            else:
                raise DSLExecutionError(f"Expected term, got '{tok}'")
        else:
            if tok in ('+', '-'):
                if i + 1 >= len(tokens):
                    raise DSLExecutionError("Trailing operator")
                term = tokens[i + 1]
                if not (INT_RE.fullmatch(term) or IDENT_RE.fullmatch(term)):
                    raise DSLExecutionError(f"Expected term after '{tok}'")
                ast.append((tok, term))
                i += 1
            else:
                raise DSLExecutionError(f"Expected operator, got '{tok}'")
            expect_term = False
        i += 1
    if expect_term:
        raise DSLExecutionError("Incomplete expression")
    return ast


def parse_script(script: str):
    statements: List[Tuple[str, List[Union[str, Tuple[str, str]]]]] = []
    for stmt in script.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = re.match(r"let\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.+)", stmt)
        if not m:
            raise DSLExecutionError(f"Invalid statement: {stmt}")
        var = m.group(1)
        expr_str = m.group(2).strip()
        expr_ast = _parse_expression(expr_str)
        statements.append((var, expr_ast))
    return statements


def execute(script: str, state: Dict[str, int]) -> Dict[str, int]:
    state = state.copy()
    for var, expr_ast in parse_script(script):
        value = _eval_expression(expr_ast, state)
        state[var] = value
    return state


def _eval_expression(ast: List[Union[str, Tuple[str, str]]], state: Dict[str, int]) -> int:
    def term_value(token: str) -> int:
        if INT_RE.fullmatch(token):
            return int(token)
        if token in state:
            return state[token]
        raise DSLExecutionError(f"Unknown variable: {token}")

    first = ast[0]
    result = term_value(first)
    for item in ast[1:]:
        op, term = item
        val = term_value(term)
        if op == '+':
            result += val
        else:
            result -= val
    return result
