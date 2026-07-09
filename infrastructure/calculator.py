import ast
import math
import operator

from .tool_registry import tool

# eval() は使わない。ast で構文解析し、許可した数値演算だけを評価する。
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: None,  # 巨大数ガードのため専用処理
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_MAX_POW_BITS = 1_000_000  # べき乗結果の概算ビット数上限
_MAX_FACTORIAL_ARG = 5_000


def _safe_factorial(n):
    if not isinstance(n, int) or n > _MAX_FACTORIAL_ARG:
        raise ValueError(f"factorial argument too large (> {_MAX_FACTORIAL_ARG})")
    return math.factorial(n)


_FUNCTIONS = {
    name: getattr(math, name)
    for name in (
        "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
        "log", "log10", "log2", "exp", "floor", "ceil",
        "degrees", "radians", "gcd", "hypot",
    )
}
_FUNCTIONS.update({
    "abs": abs, "round": round, "min": min, "max": max,
    "factorial": _safe_factorial,
})

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _safe_pow(base, exp):
    # 10**10**10 のような式でメモリ・CPU を食い潰さないための概算ガード
    if isinstance(base, int) and isinstance(exp, int) and exp > 0 and base != 0:
        if base.bit_length() * exp > _MAX_POW_BITS:
            raise ValueError("result of ** would be too large")
    return operator.pow(base, exp)


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            return _safe_pow(left, right)
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and not node.keywords
        ):
            args = [_eval_node(a) for a in node.args]
            return _FUNCTIONS[node.func.id](*args)
        raise ValueError("unsupported function call")
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ValueError(f"unknown name: {node.id}")
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


@tool(
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Evaluate a mathematical expression exactly and return the result. "
                "Use this for ANY arithmetic beyond trivial mental math - "
                "multi-digit multiplication, division, percentages, powers, roots, "
                "trigonometry - instead of computing it yourself. "
                "Supports + - * / // % ** parentheses, functions like sqrt, log, "
                "sin, cos, round, abs, min, max, factorial, gcd, and constants pi, e."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The expression, e.g. '847329 * 293847' or 'sqrt(2) * 10'",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    indicator=lambda args: f"[calculate: {args.get('expression', '')}]\n",
)
def calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval_node(tree.body)
    except ZeroDivisionError:
        return "Error: division by zero"
    except (ValueError, TypeError, OverflowError, SyntaxError) as e:
        return f"Error: {e}"
    return f"{expression.strip()} = {result}"
