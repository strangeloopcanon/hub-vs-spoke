"""Unit tests for evaluation components."""

from __future__ import annotations

from hub_vs_spoke.evaluation.cost import CostCalculator
from hub_vs_spoke.evaluation.deterministic import DeterministicEvaluator
from hub_vs_spoke.evaluation.reliability import ReliabilityScorer
from hub_vs_spoke.types import CostRecord, TopologyResult, Turn, Usage

# ---------------------------------------------------------------------------
# DeterministicEvaluator
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_match_found(self) -> None:
        result = DeterministicEvaluator.exact_match("The answer is 42.", "42")
        assert result["match"] is True

    def test_match_case_insensitive(self) -> None:
        result = DeterministicEvaluator.exact_match("Hello World", "hello world")
        assert result["match"] is True

    def test_no_match(self) -> None:
        result = DeterministicEvaluator.exact_match("The answer is 42", "43")
        assert result["match"] is False

    def test_strict_mode(self) -> None:
        result = DeterministicEvaluator.exact_match(
            "Hello World", "hello world", normalize=False
        )
        assert result["match"] is False


class TestRegexMatch:
    def test_pattern_found(self) -> None:
        result = DeterministicEvaluator.regex_match("area = 1250 sq m", r"\d+\s*sq\s*m")
        assert result["match"] is True
        assert "1250 sq m" in result["matched_text"]

    def test_pattern_not_found(self) -> None:
        result = DeterministicEvaluator.regex_match("no numbers here", r"\d+")
        assert result["match"] is False
        assert result["matched_text"] is None


class TestCodeExecution:
    def test_valid_code_succeeds(self) -> None:
        result = DeterministicEvaluator.code_execution("print('hello')")
        assert result["success"] is True
        assert "hello" in result["stdout"]

    def test_invalid_code_fails(self) -> None:
        result = DeterministicEvaluator.code_execution("raise ValueError('boom')")
        assert result["success"] is False
        assert "boom" in result["stderr"]

    def test_with_test_code(self) -> None:
        code = "def add(a, b): return a + b"
        test = "assert add(2, 3) == 5\nprint('PASS')"
        result = DeterministicEvaluator.code_execution(code, test_code=test)
        assert result["success"] is True


class TestFunctionCallCheck:
    def test_all_tools_present_and_ordered(self) -> None:
        output = (
            "First, call fetch_user(42). Then call fetch_orders(42). "
            "Next, call fetch_product(123). Finally, send_email(...)."
        )
        result = DeterministicEvaluator.function_call_check(
            output, ["fetch_user", "fetch_orders", "fetch_product", "send_email"]
        )
        assert result["all_present"] is True
        assert result["ordered"] is True
        assert len(result["missing"]) == 0

    def test_missing_tool(self) -> None:
        output = "Call fetch_user then send_email."
        result = DeterministicEvaluator.function_call_check(
            output, ["fetch_user", "fetch_orders", "send_email"]
        )
        assert result["all_present"] is False
        assert "fetch_orders" in result["missing"]

    def test_wrong_order(self) -> None:
        output = "First send_email, then fetch_user."
        result = DeterministicEvaluator.function_call_check(
            output, ["fetch_user", "send_email"]
        )
        assert result["all_present"] is True
        assert result["ordered"] is False


class TestFunctionCallCheckStructured:
    def test_sequence_checks_positional_args(self) -> None:
        output = (
            "1) calculate('366 * 24 * 60 * 60') -> 31622400\n"
            "2) format_report(title='Leap year seconds', sections=['calc', 'result']) -> '...'\n"
        )
        spec = {
            "sequence": [
                {"tool": "calculate", "args": [{"evals_to": 31622400}]},
                {"tool": "format_report"},
            ],
            "require_text": ["31622400"],
        }
        result = DeterministicEvaluator.function_call_check(output, spec)
        assert result["match"] is True

    def test_sequence_fails_on_wrong_math(self) -> None:
        output = "calculate('365 * 24 * 60 * 60') -> 31536000\nformat_report(...)"
        spec = {
            "sequence": [
                {"tool": "calculate", "args": [{"evals_to": 31622400}]},
                {"tool": "format_report"},
            ]
        }
        result = DeterministicEvaluator.function_call_check(output, spec)
        assert result["match"] is False

    def test_scenarios_requires_hit_and_miss_paths(self) -> None:
        output = (
            "Cache hit:\n"
            "- cache_get(key='user_stats') -> '{\"total\": 10}'\n"
            "- log_metric(name='cache_hit', value=1)\n\n"
            "Cache miss:\n"
            "- cache_get(key='user_stats') -> None\n"
            "- query_db(sql='SELECT count(*) as total, avg(score) as avg FROM users') -> []\n"
            "- cache_set(key='user_stats', value='...', ttl=300) -> True\n"
            "- log_metric(name='cache_miss', value=1)\n"
            "- log_metric(name='query_latency_ms', value=12.3)\n"
        )
        spec = {
            "require_any_text": ["cache hit", "cache-hit"],
            "scenarios": {
                "hit": [
                    {"tool": "cache_get", "kwargs": {"key": "user_stats"}},
                    {"tool": "log_metric", "kwargs": {"name": {"regex": "hit"}}},
                ],
                "miss": [
                    {"tool": "cache_get", "kwargs": {"key": "user_stats"}},
                    {
                        "tool": "query_db",
                        "kwargs": {
                            "sql": {"contains": "select count(*) as total, avg(score) as avg"}
                        },
                    },
                    {"tool": "cache_set", "kwargs": {"ttl": 300}},
                    {"tool": "log_metric", "kwargs": {"name": {"regex": "miss"}}},
                    {"tool": "log_metric", "kwargs": {"name": {"regex": "latency|query"}}},
                ],
            },
        }
        result = DeterministicEvaluator.function_call_check(output, spec)
        assert result["match"] is True

    def test_scenarios_fails_if_only_one_path(self) -> None:
        output = (
            "Cache miss only:\n"
            "cache_get(key='user_stats') -> None\n"
            "query_db(sql='SELECT count(*) as total, avg(score) as avg FROM users')\n"
            "cache_set(key='user_stats', value='...', ttl=300)\n"
            "log_metric(name='cache_miss', value=1)\n"
            "log_metric(name='query_latency_ms', value=12.3)\n"
        )
        spec = {
            "scenarios": {
                "hit": [
                    {"tool": "cache_get", "kwargs": {"key": "user_stats"}},
                    {"tool": "log_metric", "kwargs": {"name": {"regex": "hit"}}},
                ],
                "miss": [
                    {"tool": "cache_get", "kwargs": {"key": "user_stats"}},
                    {"tool": "query_db"},
                ],
            }
        }
        result = DeterministicEvaluator.function_call_check(output, spec)
        assert result["match"] is False


# ---------------------------------------------------------------------------
# CostCalculator
# ---------------------------------------------------------------------------


class TestCostCalculator:
    def test_cost_from_usage_known_model(self) -> None:
        usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = CostCalculator.cost_from_usage("gpt-4o", usage)
        # gpt-4o: $2.50 input + $10.00 output per 1M tokens = $12.50
        assert abs(cost - 12.50) < 0.01

    def test_cost_from_usage_unknown_model(self) -> None:
        usage = Usage(input_tokens=1000, output_tokens=1000)
        cost = CostCalculator.cost_from_usage("unknown-model", usage)
        assert cost == 0.0

    def test_available_models(self) -> None:
        models = CostCalculator.available_models()
        assert "gpt-4o" in models
        assert "claude-sonnet-4-20250514" in models


class TestCostRecord:
    def test_from_usage(self) -> None:
        usage = Usage(input_tokens=500_000, output_tokens=100_000)
        record = CostRecord.from_usage("gpt-4o-mini", usage)
        # gpt-4o-mini: $0.15/1M input, $0.60/1M output
        expected_input = 0.5 * 0.15
        expected_output = 0.1 * 0.60
        assert abs(record.input_cost_usd - expected_input) < 0.001
        assert abs(record.output_cost_usd - expected_output) < 0.001
        assert abs(record.total_cost_usd - (expected_input + expected_output)) < 0.001


# ---------------------------------------------------------------------------
# ReliabilityScorer
# ---------------------------------------------------------------------------


def _make_result(success: bool, n_turns: int = 3, n_errors: int = 0) -> TopologyResult:
    turns = [
        Turn(
            from_agent="a",
            to_agent="b",
            message="msg",
            response="resp" if i >= n_errors else "",
            error="fail" if i < n_errors else None,
        )
        for i in range(n_turns)
    ]
    return TopologyResult(
        topology_name="test",
        task_id="t",
        final_answer="answer" if success else "",
        turns=turns,
        errors=["err"] * n_errors,
    )


class TestReliabilityScorer:
    def test_single_success(self) -> None:
        result = _make_result(success=True, n_turns=5, n_errors=0)
        score = ReliabilityScorer.score_single(result)
        assert score["success"] is True
        assert score["error_rate"] == 0.0

    def test_single_with_errors(self) -> None:
        result = _make_result(success=True, n_turns=5, n_errors=2)
        score = ReliabilityScorer.score_single(result)
        assert score["error_turns"] == 2
        assert abs(score["error_rate"] - 0.4) < 0.01

    def test_batch_scoring(self) -> None:
        results = [_make_result(True), _make_result(True), _make_result(False)]
        batch = ReliabilityScorer.score_batch(results)
        assert batch["total_runs"] == 3
        assert abs(batch["success_rate"] - 2 / 3) < 0.01

    def test_compare_topologies(self) -> None:
        hs = [_make_result(True), _make_result(True), _make_result(True)]
        ss = [_make_result(True), _make_result(False)]
        comparison = ReliabilityScorer.compare_topologies(hs, ss)
        assert comparison["more_reliable"] == "hub-spoke"
        assert comparison["success_rate_delta"] > 0

    def test_empty_batch(self) -> None:
        batch = ReliabilityScorer.score_batch([])
        assert batch["total_runs"] == 0
        assert batch["success_rate"] == 0.0
