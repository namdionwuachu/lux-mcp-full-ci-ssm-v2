"""Tiny agent registry/router used by orchestrator."""
from __future__ import annotations
from typing import Dict, Any, Callable, Optional
import time, uuid
import logging

logger = logging.getLogger(__name__)

AgentFn = Callable[[Dict[str, Any]], Dict[str, Any]]

class MCP:
    def __init__(self) -> None:
        self._agents: Dict[str, AgentFn] = {}
        self._meta: Dict[str, Any] = {}

    def register(self, name: str, fn: AgentFn, meta: Optional[Dict[str, Any]] = None) -> None:
        if not callable(fn):
            raise TypeError(f"Agent '{name}' is not callable")
        self._agents[name] = fn
        if meta:
            self._meta[name] = meta

    def route(self, task: Dict[str, Any]) -> Dict[str, Any]:
        agent = task.get("agent")
        corr_id = task.get("task_id") or task.get("request_id") or str(uuid.uuid4())

        if agent not in self._agents:
            return {
                "status": "error",
                "error": f"unknown agent: {agent}",
                "agent": agent,
                "task_id": corr_id,
                "latency_ms": 0,
            }

        fn = self._agents[agent]
        t0 = time.time()
        try:
            result = fn(task)  # call agent
            if not isinstance(result, dict):
                result = {"status": "ok", "data": result}
            out = dict(result)  # don’t mutate agent’s original
            status = out.get("status", "ok")
        except Exception as e:
            logger.exception("Agent '%s' failed (task_id=%s)", agent, corr_id)
            out = {"status": "error", "error": str(e)}
            status = "error"
        finally:
            latency_ms = int((time.time() - t0) * 1000)

        # annotate
        out.setdefault("status", status)
        out["latency_ms"] = latency_ms
        out["agent"] = agent
        out["task_id"] = corr_id

        # optionally surface agent meta
        if agent in self._meta:
            out.setdefault("meta", self._meta[agent])

        return out
