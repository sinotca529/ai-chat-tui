import math

from infrastructure.calculator import calculate


def _result(expression: str) -> str:
    return calculate({"expression": expression})


def test_basic_arithmetic():
    assert _result("1 + 2 * 3") == "1 + 2 * 3 = 7"
    assert _result("(1 + 2) * 3") == "(1 + 2) * 3 = 9"
    assert _result("7 / 2") == "7 / 2 = 3.5"
    assert _result("7 // 2") == "7 // 2 = 3"
    assert _result("7 % 3") == "7 % 3 = 1"
    assert _result("-5 + +3") == "-5 + +3 = -2"


def test_large_multiplication_is_exact():
    """LLM が暗算を誤る桁数でも正確に計算できる"""
    assert _result("847329 * 293847") == f"847329 * 293847 = {847329 * 293847}"


def test_functions_and_constants():
    assert _result("sqrt(2) * 10") == f"sqrt(2) * 10 = {math.sqrt(2) * 10}"
    assert _result("round(pi, 3)") == "round(pi, 3) = 3.142"
    assert _result("max(3, 1, 2)") == "max(3, 1, 2) = 3"
    assert _result("factorial(10)") == "factorial(10) = 3628800"
    assert _result("gcd(12, 18)") == "gcd(12, 18) = 6"


def test_division_by_zero():
    assert _result("1 / 0") == "Error: division by zero"


def test_syntax_error_returns_message():
    assert _result("1 +").startswith("Error:")


def test_unknown_name_rejected():
    assert _result("x + 1").startswith("Error:")


def test_code_injection_is_rejected():
    """任意コード実行につながる構文はすべて拒否される"""
    assert _result("__import__('os').system('ls')").startswith("Error:")
    assert _result("().__class__").startswith("Error:")
    assert _result("'a' * 100").startswith("Error:")
    assert _result("[1,2][0]").startswith("Error:")
    assert _result("lambda: 1").startswith("Error:")
    assert _result("pi if 1 else e").startswith("Error:")


def test_huge_power_is_rejected():
    """10**10**10 のような式でメモリ・CPU を食い潰さない"""
    assert _result("10 ** 10 ** 10").startswith("Error:")
    assert _result("2 ** 1000").endswith(str(2 ** 1000))  # 常識的な範囲は通る


def test_huge_factorial_is_rejected():
    assert _result("factorial(10 ** 6)").startswith("Error:")


def test_boolean_literals_rejected():
    assert _result("True + 1").startswith("Error:")


def test_tool_definition_and_indicator():
    assert calculate.definition["function"]["name"] == "calculate"
    assert "expression" in calculate.definition["function"]["parameters"]["required"]
    assert calculate.indicator({"expression": "1+1"}) == "[calculate: 1+1]\n"
