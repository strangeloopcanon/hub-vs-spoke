"""LLM router adapter for Codex and Cursor CLI-backed workers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_economy.json_extract import extract_json_object
from agent_economy.llm_openai import Usage
from agent_economy.model_refs import split_provider_model
from pydantic import BaseModel


def _timeout_seconds(env_name: str, default: int = 900) -> int:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    return max(1, int(raw))


def _tail(text: str, *, max_chars: int = 1200) -> str:
    value = str(text or "").strip()
    return value[-max_chars:]


def _combine_prompt(system: str, user: str, suffix: str = "") -> str:
    parts = [
        "## System instructions",
        system.strip(),
        "",
        "## User task",
        user.strip(),
    ]
    if suffix.strip():
        parts.extend(["", suffix.strip()])
    return "\n".join(parts).strip() + "\n"


def _parse_codex_usage(jsonl_text: str) -> Usage:
    calls = 0
    input_tokens = 0
    output_tokens = 0
    for raw_line in str(jsonl_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "turn.completed":
            continue
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        calls += 1
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
    return Usage(calls=calls, input_tokens=input_tokens, output_tokens=output_tokens)


def _last_codex_agent_message(jsonl_text: str) -> str:
    last = ""
    for raw_line in str(jsonl_text or "").splitlines():
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        item = payload.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            last = str(item.get("text") or "")
    return last.strip()


def _parse_cursor_response(stdout_text: str) -> tuple[str, Usage]:
    payload = json.loads(str(stdout_text or "").strip())
    if not isinstance(payload, dict):
        raise ValueError("cursor-agent returned non-object JSON")
    if payload.get("is_error"):
        raise RuntimeError(str(payload.get("result") or "cursor-agent returned an error"))

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    # Cursor reports prompt-cache traffic separately. Treat cache read/write tokens as
    # input-like tokens so benchmark cost accounting does not silently drop them.
    input_tokens = (
        int(usage.get("inputTokens") or 0)
        + int(usage.get("cacheReadTokens") or 0)
        + int(usage.get("cacheWriteTokens") or 0)
    )
    output_tokens = int(usage.get("outputTokens") or 0)
    return str(payload.get("result") or "").strip(), Usage(
        calls=1,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


@dataclass
class CliCapableRouter:
    """Routes regular model refs to an LLMRouter and CLI refs to local CLIs.

    Supported CLI model_ref prefixes:
    - ``codex:<model>`` runs ``codex exec -m <model>``.
    - ``cursor:<model>`` runs ``cursor-agent --model <model>``.
    """

    delegate: Any
    codex_cwd: Path = Path("/tmp")
    cursor_workspace: Path = Path("/tmp")

    def call_text(
        self,
        *,
        model_ref: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_output_tokens: int = 3000,
        reasoning_effort: str | None = None,
        text_verbosity: str | None = None,
        max_retries: int = 3,
    ) -> tuple[str, Usage]:
        provider, model = split_provider_model(model_ref)
        if provider == "codex":
            return self._call_codex(model=model, prompt=_combine_prompt(system, user))
        if provider == "cursor":
            return self._call_cursor(model=model, prompt=_combine_prompt(system, user))
        return self.delegate.call_text(
            model_ref=model_ref,
            system=system,
            user=user,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            reasoning_effort=reasoning_effort,
            text_verbosity=text_verbosity,
            max_retries=max_retries,
        )

    def call_json(
        self,
        *,
        model_ref: str,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_output_tokens: int = 1500,
        reasoning_effort: str | None = None,
        text_verbosity: str | None = None,
        max_retries: int = 3,
    ) -> tuple[BaseModel, Usage, str]:
        provider, model = split_provider_model(model_ref)
        if provider not in {"codex", "cursor"}:
            return self.delegate.call_json(
                model_ref=model_ref,
                system=system,
                user=user,
                schema=schema,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                reasoning_effort=reasoning_effort,
                text_verbosity=text_verbosity,
                max_retries=max_retries,
            )

        suffix = (
            "Return only one valid JSON object matching this JSON schema.\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=True)}"
        )
        prompt = _combine_prompt(system, user, suffix)
        if provider == "codex":
            raw, usage = self._call_codex(model=model, prompt=prompt)
        else:
            raw, usage = self._call_cursor(model=model, prompt=prompt)
        parsed = schema.model_validate(extract_json_object(raw))
        return parsed, usage, raw

    def _call_codex(self, *, model: str, prompt: str) -> tuple[str, Usage]:
        self.codex_cwd.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="hvs-codex-", suffix=".txt", delete=False) as f:
            output_path = Path(f.name)
        try:
            cmd = [
                "codex",
                "-a",
                "never",
                "exec",
                "-m",
                model,
                "--ephemeral",
                "--ignore-rules",
                "--ignore-user-config",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-C",
                str(self.codex_cwd),
                "--json",
                "--output-last-message",
                str(output_path),
                "-",
            ]
            proc = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=_timeout_seconds("HVS_CODEX_TIMEOUT_S"),
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"codex exec failed rc={proc.returncode}: {_tail(proc.stderr)}"
                )
            text = output_path.read_text(encoding="utf-8").strip()
            if not text:
                text = _last_codex_agent_message(proc.stdout)
            if not text:
                raise RuntimeError("codex exec returned no final message")
            return text, _parse_codex_usage(proc.stdout)
        finally:
            output_path.unlink(missing_ok=True)

    def _call_cursor(self, *, model: str, prompt: str) -> tuple[str, Usage]:
        self.cursor_workspace.mkdir(parents=True, exist_ok=True)
        cmd = [
            "cursor-agent",
            "--model",
            model,
            "--print",
            "--output-format",
            "json",
            "--mode",
            "ask",
            "--trust",
            "--workspace",
            str(self.cursor_workspace),
            prompt,
        ]
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=_timeout_seconds("HVS_CURSOR_TIMEOUT_S"),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"cursor-agent failed rc={proc.returncode}: {_tail(proc.stderr or proc.stdout)}"
            )
        return _parse_cursor_response(proc.stdout)
