"""Allow / ask / block policy engine, driven by rules.yaml."""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from .config import RULES_PATH


@dataclass
class Decision:
    action: str  # allow | ask | block
    risk: str  # low | medium | high
    reason: str
    rule_name: Optional[str] = None


@dataclass
class ToolEvent:
    """Normalized view of an action an AI agent is about to take."""
    tool_name: str
    strings: list[str] = field(default_factory=list)  # every string arg value, flattened

    @classmethod
    def from_args(cls, tool_name: str, args: dict[str, Any]) -> "ToolEvent":
        return cls(tool_name=tool_name or "", strings=_flatten_strings(args))


def _flatten_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten_strings(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_flatten_strings(v))
    return out


class PolicyEngine:
    def __init__(self, rules_path=RULES_PATH):
        self.rules_path = rules_path
        self.rules: list[dict] = []
        self.default_action = "allow"
        self.default_risk = "low"
        self.reload()

    def reload(self) -> None:
        with open(self.rules_path, "r") as f:
            data = yaml.safe_load(f) or {}
        self.rules = data.get("rules", [])
        self.default_action = data.get("default_action", "allow")
        self.default_risk = data.get("default_risk", "low")

    def evaluate(self, event: ToolEvent) -> Decision:
        for rule in self.rules:
            if self._matches(rule.get("match", {}), event):
                return Decision(
                    action=rule.get("action", self.default_action),
                    risk=rule.get("risk", self.default_risk),
                    reason=rule.get("reason", ""),
                    rule_name=rule.get("name"),
                )
        return Decision(action=self.default_action, risk=self.default_risk, reason="No matching rule")

    def _matches(self, match: dict, event: ToolEvent) -> bool:
        if not match:
            return True

        tool_patterns = match.get("tool")
        if tool_patterns:
            if not any(fnmatch.fnmatch(event.tool_name, p) for p in tool_patterns):
                return False

        for key, substrs in (
            ("path_prefix", match.get("path_prefix")),
            ("path_contains", match.get("path_contains")),
            ("command_contains", match.get("command_contains")),
            ("domain_contains", match.get("domain_contains")),
        ):
            if not substrs:
                continue
            check = _prefix_check if key == "path_prefix" else _contains_check
            if not any(check(s, needle) for s in event.strings for needle in substrs):
                return False

        return True


def _contains_check(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _prefix_check(haystack: str, needle: str) -> bool:
    return haystack.startswith(needle)


def summarize_target(event: ToolEvent, max_len: int = 120) -> str:
    text = " ".join(event.strings)
    return text[:max_len] + ("…" if len(text) > max_len else "")
