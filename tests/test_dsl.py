import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from blockchain_demo import dsl


def test_valid_script():
    script = "let a = 1; let b = a + 2;"
    result = dsl.execute(script, {})
    assert result == {"a": 1, "b": 3}


def test_invalid_syntax():
    script = "let a 1"
    with pytest.raises(dsl.DSLExecutionError):
        dsl.execute(script, {})


def test_sequential_execution():
    script = "let a = 1; let b = a + 1; let c = b + a + 2"
    result = dsl.execute(script, {})
    assert result == {"a": 1, "b": 2, "c": 5}


def test_unknown_variable():
    script = "let b = c + 1"
    with pytest.raises(dsl.DSLExecutionError):
        dsl.execute(script, {})
