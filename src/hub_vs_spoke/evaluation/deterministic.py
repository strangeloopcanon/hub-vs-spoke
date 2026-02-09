"""Deterministic evaluators: exact match, regex, code execution."""

from __future__ import annotations

import ast
import itertools
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any


class DeterministicEvaluator:
    """Evaluate outputs using deterministic (non-LLM) methods."""

    @staticmethod
    def exact_match(output: str, expected: str, *, normalize: bool = True) -> dict[str, Any]:
        """Check if output contains the expected answer.

        With normalize=True, comparison is case-insensitive and whitespace-collapsed.
        """
        if normalize:
            out = " ".join(output.lower().split())
            exp = " ".join(expected.lower().split())
        else:
            out, exp = output, expected

        return {"match": exp in out, "expected": expected, "method": "exact_match"}

    @staticmethod
    def regex_match(output: str, pattern: str) -> dict[str, Any]:
        """Check if output matches a regex pattern."""
        found = re.search(pattern, output, re.IGNORECASE | re.DOTALL)
        return {
            "match": found is not None,
            "pattern": pattern,
            "matched_text": found.group(0) if found else None,
            "method": "regex_match",
        }

    @staticmethod
    def code_execution(
        code: str,
        *,
        test_code: str = "",
        timeout: int = 10,
    ) -> dict[str, Any]:
        """Execute Python code in a subprocess and check for errors.

        If test_code is provided, it is appended after the main code.
        """
        full_code = f"{code}\n\n{test_code}" if test_code else code

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(full_code)
            temp_path = f.name

        try:
            result = subprocess.run(
                ["python", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode,
                "method": "code_execution",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout}s",
                "returncode": -1,
                "method": "code_execution",
            }
        finally:
            os.unlink(temp_path)

    @staticmethod
    def function_call_check(
        output: str,
        expected_tools: list[str] | list[dict[str, Any]] | dict[str, Any],
    ) -> dict[str, Any]:
        """Check that the output includes the expected tool/function calls.

        Backwards compatible modes:
        - If expected_tools is a list[str], we do a simple substring + ordering check.

        Structured mode:
        - If expected_tools is a list[dict], it is treated as an ordered call sequence.
        - If expected_tools is a dict, supported keys:
          - sequence: list[call_spec]
          - scenarios: dict[str, list[call_spec]] (requires each scenario sequence)
          - require_text: list[str] (all must appear in output, case-insensitive)
          - require_any_text: list[str] (at least one must appear in output)
        """
        if isinstance(expected_tools, list) and all(isinstance(t, str) for t in expected_tools):
            return _legacy_function_call_check(output, expected_tools)

        spec: dict[str, Any] = (
            {"sequence": expected_tools} if isinstance(expected_tools, list) else expected_tools
        )

        require_text = [str(s) for s in spec.get("require_text", [])]
        require_any_text = [str(s) for s in spec.get("require_any_text", [])]
        require_text_missing = [s for s in require_text if s.lower() not in output.lower()]
        require_any_text_ok = True
        if require_any_text:
            require_any_text_ok = any(s.lower() in output.lower() for s in require_any_text)

        # Build tool name universe for parsing.
        tool_names: list[str] = []
        if "sequence" in spec:
            tool_names.extend(_tool_names_from_sequence(spec["sequence"]))
        if "scenarios" in spec:
            for seq in spec["scenarios"].values():
                tool_names.extend(_tool_names_from_sequence(seq))
        tool_names = sorted({t.lower() for t in tool_names})

        parsed_calls = _extract_tool_calls(output, tool_names)

        match = True
        details: dict[str, Any] = {}

        if require_text_missing:
            match = False
        if not require_any_text_ok:
            match = False

        if "sequence" in spec:
            ok, seq_details = _match_sequence(parsed_calls, spec["sequence"])
            details["sequence"] = seq_details
            match = match and ok

        if "scenarios" in spec:
            ok, scen_details = _match_scenarios(parsed_calls, spec["scenarios"])
            details["scenarios"] = scen_details
            match = match and ok

        return {
            "match": match,
            "require_text_missing": require_text_missing,
            "require_any_text_ok": require_any_text_ok,
            "expected": spec,
            "parsed_calls": [c.as_dict() for c in parsed_calls],
            "details": details,
            "method": "function_call_check",
        }


def _legacy_function_call_check(output: str, expected_tools: list[str]) -> dict[str, Any]:
    """Legacy substring-based check (kept for backward compatibility)."""
    output_lower = output.lower()
    found_tools = [t for t in expected_tools if t.lower() in output_lower]

    # Check ordering: each tool should appear after the previous one
    ordered = True
    last_pos = -1
    for tool in expected_tools:
        pos = output_lower.find(tool.lower())
        if pos == -1 or pos < last_pos:
            ordered = False
            break
        last_pos = pos

    return {
        "all_present": len(found_tools) == len(expected_tools),
        "ordered": ordered,
        "expected": expected_tools,
        "found": found_tools,
        "missing": [t for t in expected_tools if t not in found_tools],
        "method": "function_call_check",
    }


@dataclass
class _ToolCall:
    tool: str
    args: list[Any]
    kwargs: dict[str, Any]
    raw_args: str
    start: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "kwargs": self.kwargs,
            "raw_args": self.raw_args,
            "start": self.start,
        }


def _tool_names_from_sequence(seq: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in seq:
        any_of = item.get("any_of")
        if isinstance(any_of, list):
            for alt in any_of:
                if isinstance(alt, dict):
                    tool = alt.get("tool")
                    if isinstance(tool, str) and tool:
                        names.append(tool)

        tool = item.get("tool")
        if isinstance(tool, str) and tool:
            names.append(tool)
    return names


def _extract_tool_calls(output: str, tool_names: list[str]) -> list[_ToolCall]:
    """Extract tool calls like tool_name(...) from freeform text."""
    if not tool_names:
        return []

    # Word boundary + optional whitespace before '('
    pattern = re.compile(
        r"(?i)\b(?P<tool>" + "|".join(re.escape(t) for t in tool_names) + r")\s*\("
    )
    calls: list[_ToolCall] = []
    for m in pattern.finditer(output):
        tool = (m.group("tool") or "").lower()
        open_paren = m.end() - 1
        raw_args, _close_paren = _extract_paren_args(output, open_paren)
        args, kwargs = _parse_call_args(raw_args)
        calls.append(
            _ToolCall(tool=tool, args=args, kwargs=kwargs, raw_args=raw_args, start=m.start())
        )
    return calls


def _extract_paren_args(text: str, open_paren: int) -> tuple[str, int | None]:
    """Return (args, close_paren_index) for the parenthesized content starting at open_paren."""
    i = open_paren + 1
    depth = 1
    in_str: str | None = None
    escape = False
    while i < len(text):
        ch = text[i]
        if in_str is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
        else:
            if ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[open_paren + 1 : i], i
        i += 1
    # Unbalanced parentheses; return best-effort.
    return text[open_paren + 1 :], None


def _parse_call_args(raw_args: str) -> tuple[list[Any], dict[str, Any]]:
    """Parse a tool call arg string into (args, kwargs) using a safe AST parse."""
    if not raw_args.strip():
        return [], {}

    try:
        node = ast.parse(f"f({raw_args})", mode="eval")
    except SyntaxError:
        return [], {}

    if not isinstance(node, ast.Expression) or not isinstance(node.body, ast.Call):
        return [], {}

    call = node.body
    args = [_ast_value(a) for a in call.args]
    kwargs: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            # e.g. **kwargs; preserve as raw string
            kwargs["**"] = ast.unparse(kw.value)
        else:
            kwargs[kw.arg] = _ast_value(kw.value)
    return args, kwargs


def _ast_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    return ast.unparse(node)


def _match_sequence(
    calls: list[_ToolCall],
    seq: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    """Check an ordered sequence of expected calls appears in parsed calls."""
    expected_seq = [_normalize_call_spec(s) for s in seq]
    idx = 0
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for spec in expected_seq:
        found_at = None
        while idx < len(calls):
            if _call_matches_spec(calls[idx], spec):
                found_at = idx
                matched.append({"expected": spec, "found": calls[idx].as_dict(), "index": idx})
                idx += 1
                break
            idx += 1
        if found_at is None:
            missing.append(spec)

    ok = len(missing) == 0
    return ok, {"matched": matched, "missing": missing, "total_calls": len(calls)}


def _match_scenarios(
    calls: list[_ToolCall], scenarios: dict[str, list[dict[str, Any]]]
) -> tuple[bool, dict[str, Any]]:
    """Require each named scenario sequence to appear as a non-overlapping subsequence."""
    scenario_specs = {k: [_normalize_call_spec(s) for s in v] for k, v in scenarios.items()}
    names = list(scenario_specs.keys())

    for perm in itertools.permutations(names):
        cursor = 0
        matched: dict[str, Any] = {}
        ok = True
        for name in perm:
            seq = scenario_specs[name]
            seq_ok, seq_details = _match_sequence(calls[cursor:], seq)
            if not seq_ok:
                ok = False
                break
            # Translate indices back to absolute.
            last_idx = max((m["index"] for m in seq_details["matched"]), default=-1)
            for m in seq_details["matched"]:
                m["index"] += cursor
            matched[name] = seq_details
            cursor = cursor + last_idx + 1
        if ok:
            return True, {"matched": matched, "order": list(perm)}

    # If no permutation matches, report per-scenario best-effort matches from start.
    best_effort = {}
    for name, seq in scenario_specs.items():
        ok, details = _match_sequence(calls, seq)
        best_effort[name] = {"ok": ok, **details}
    return False, {"matched": {}, "best_effort": best_effort}


def _normalize_call_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Shallow-normalize a call spec."""
    any_of = spec.get("any_of")
    if any_of is not None:
        if not isinstance(any_of, list) or not any(isinstance(x, dict) for x in any_of):
            raise ValueError("call_spec any_of must be a list of call_spec dicts")
        return {"any_of": [_normalize_call_spec(x) for x in any_of if isinstance(x, dict)]}

    tool = spec.get("tool")
    if not isinstance(tool, str) or not tool:
        raise ValueError("call_spec missing required 'tool' field")
    norm = {"tool": tool.lower()}
    if "args" in spec:
        norm["args"] = spec["args"]
    if "kwargs" in spec:
        norm["kwargs"] = spec["kwargs"]
    return norm


def _call_matches_spec(call: _ToolCall, spec: dict[str, Any]) -> bool:
    any_of = spec.get("any_of")
    if any_of is not None:
        return isinstance(any_of, list) and any(
            isinstance(alt, dict) and _call_matches_spec(call, alt) for alt in any_of
        )

    if call.tool.lower() != str(spec.get("tool", "")).lower():
        return False

    exp_args = spec.get("args", [])
    if exp_args:
        if not isinstance(exp_args, list):
            return False
        if len(call.args) < len(exp_args):
            return False
        for i, exp in enumerate(exp_args):
            if not _match_value(call.args[i], exp):
                return False

    exp_kwargs = spec.get("kwargs", {})
    if exp_kwargs:
        if not isinstance(exp_kwargs, dict):
            return False
        for k, exp in exp_kwargs.items():
            if k not in call.kwargs:
                return False
            if not _match_value(call.kwargs[k], exp):
                return False

    return True


def _match_value(actual: Any, expectation: Any) -> bool:
    """Match a value against an expectation.

    expectation can be:
    - a primitive (str/int/float/bool/None) meaning equality (string is case-insensitive)
    - a dict with one of:
      - value: exact value
      - contains: substring (case-insensitive, whitespace-collapsed)
      - regex: regex pattern
      - evals_to: numeric; evaluate arithmetic expression and compare
      - any_of: list[expectation]
    """
    if isinstance(expectation, dict):
        if expectation.get("any") is True:
            return True

        if "any_of" in expectation:
            options = expectation.get("any_of", [])
            return isinstance(options, list) and any(_match_value(actual, opt) for opt in options)

        if "value" in expectation:
            return _values_equal(actual, expectation.get("value"))

        if "contains" in expectation:
            if not isinstance(actual, str):
                return False
            needle = str(expectation.get("contains", ""))
            return _norm_text(needle) in _norm_text(actual)

        if "regex" in expectation:
            pat = str(expectation.get("regex", ""))
            return re.search(pat, str(actual), flags=re.IGNORECASE | re.DOTALL) is not None

        if "evals_to" in expectation:
            target = expectation.get("evals_to")
            try:
                target_num = float(target)
            except (TypeError, ValueError):
                return False

            if isinstance(actual, (int, float)):
                return abs(float(actual) - target_num) < 1e-6
            if isinstance(actual, str):
                evaluated = _safe_eval_arithmetic(actual)
                return evaluated is not None and abs(evaluated - target_num) < 1e-6
            return False

        return False

    return _values_equal(actual, expectation)


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return _norm_text(a) == _norm_text(b)
    return a == b


def _norm_text(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _safe_eval_arithmetic(expr: str) -> float | None:
    """Safely evaluate a simple arithmetic expression (no names/calls)."""
    try:
        node = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None

    def _eval(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            v = _eval(n.operand)
            return v if isinstance(n.op, ast.UAdd) else -v
        if isinstance(n, ast.BinOp) and isinstance(
            n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
        ):
            left = _eval(n.left)
            right = _eval(n.right)
            if isinstance(n.op, ast.Add):
                return left + right
            if isinstance(n.op, ast.Sub):
                return left - right
            if isinstance(n.op, ast.Mult):
                return left * right
            if isinstance(n.op, ast.Div):
                return left / right
            if isinstance(n.op, ast.FloorDiv):
                return left // right
            if isinstance(n.op, ast.Mod):
                return left % right
            return left**right

        raise ValueError("unsupported expression")

    try:
        return _eval(node)
    except Exception:
        return None
