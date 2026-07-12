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
    # ast.Pow は巨大数ガードのため _eval_node 内で専用処理
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
    match node:
        # bool は int のサブクラスなので、数値より先に弾く
        case ast.Constant(value=bool() as value):
            raise ValueError(f"unsupported constant: {value!r}")
        case ast.Constant(value=(int() | float()) as value):
            return value
        case ast.Constant(value=value):
            raise ValueError(f"unsupported constant: {value!r}")

        case ast.BinOp(left=left, op=ast.Pow(), right=right):
            return _safe_pow(_eval_node(left), _eval_node(right))
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BIN_OPS:
            return _BIN_OPS[type(op)](_eval_node(left), _eval_node(right))

        case ast.UnaryOp(op=op, operand=operand) if type(op) in _UNARY_OPS:
            return _UNARY_OPS[type(op)](_eval_node(operand))

        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in _FUNCTIONS:
            return _FUNCTIONS[name](*[_eval_node(a) for a in args])
        case ast.Call():
            raise ValueError("unsupported function call")

        case ast.Name(id=name) if name in _CONSTANTS:
            return _CONSTANTS[name]
        case ast.Name(id=name):
            raise ValueError(f"unknown name: {name}")

        case _:
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
