"""Tiny agent registry/router used by orchestrator."""
from typing import Dict, Any, Callable
import time, uuid
class MCP:
    def __init__(self): self._agents: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
    def register(self, name: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]], meta=None): self._agents[name] = fn
    def route(self, task: Dict[str, Any]) -> Dict[str, Any]:
        agent = task.get("agent")
        if agent not in self._agents: return {"status":"error","error":f"unknown agent: {agent}"}
        t0=time.time(); out=self._agents[agent](task); out["latency_ms"]=int((time.time()-t0)*1000); out["agent"]=agent; out["task_id"]=str(uuid.uuid4()); return out
