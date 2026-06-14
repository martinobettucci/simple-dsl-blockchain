"""Minimal transactional DSL operating on the global integer ``state``.

Grammar (SPECIFICATIONS.md §20)::

    SCRIPT := STMT (';' STMT)* ';'?
    STMT   := 'let' IDENT '=' EXPR
    EXPR   := TERM (('+'|'-') TERM)*
    TERM   := IDENT | INT
    IDENT  := [a-zA-Z_][a-zA-Z0-9_]*
    INT    := [0-9]+

Rules: statements run sequentially (a later statement sees earlier writes);
only integers and ``+``/``-`` are supported; an unknown variable raises (strict
mode, §20).  The DSL never touches balances (state vs balances separation, §5.1).
"""

import re
from typing import Dict, List, Tuple

_IDENT = r"[a-zA-Z_][a-zA-Z0-9_]*"
_INT = r"[0-9]+"
_TERM_RE = re.compile(rf"\s*(?P<term>{_IDENT}|{_INT})")
_OP_RE = re.compile(r"\s*(?P<op>[+\-])")
_STMT_RE = re.compile(rf"^\s*let\s+(?P<var>{_IDENT})\s*=\s*(?P<expr>.+)$", re.DOTALL)

# A parsed expression is a list of (op, term) pairs; the first op is "+".
Expr = List[Tuple[str, str]]
Stmt = Tuple[str, Expr]


class DSLExecutionError(Exception):
    """Raised for any DSL syntax or evaluation error."""


def _parse_expression(expr: str) -> Expr:
    expr = expr.strip()
    if not expr:
        raise DSLExecutionError("Empty expression")
    m = _TERM_RE.match(expr, 0)
    if not m:
        raise DSLExecutionError(f"Expected a term at start of: '{expr}'")
    terms: Expr = [("+", m.group("term"))]
    pos = m.end()
    while pos < len(expr):
        mo = _OP_RE.match(expr, pos)
        if not mo:
            raise DSLExecutionError(f"Expected '+' or '-' near: '{expr[pos:].strip()}'")
        pos = mo.end()
        mt = _TERM_RE.match(expr, pos)
        if not mt:
            raise DSLExecutionError(f"Expected a term after '{mo.group('op')}'")
        terms.append((mo.group("op"), mt.group("term")))
        pos = mt.end()
    return terms


def parse_script(script: str) -> List[Stmt]:
    """Parse a script into ``[(target_var, expr), ...]`` or raise."""
    statements: List[Stmt] = []
    for raw in script.split(";"):
        if not raw.strip():
            continue
        m = _STMT_RE.match(raw)
        if not m:
            raise DSLExecutionError(f"Invalid statement: '{raw.strip()}'")
        statements.append((m.group("var"), _parse_expression(m.group("expr"))))
    return statements


def _eval_term(token: str, state: Dict[str, int]) -> int:
    if token.isdigit():
        return int(token)
    if token in state:
        return int(state[token])
    raise DSLExecutionError(f"Unknown variable: {token}")


def execute(script: str, state: Dict[str, int]) -> Dict[str, int]:
    """Execute ``script`` against a *copy* of ``state`` and return the result."""
    new_state = dict(state)
    for var, terms in parse_script(script):
        total = 0
        for op, token in terms:
            val = _eval_term(token, new_state)
            total += val if op == "+" else -val
        new_state[var] = total
    return new_state
