"""
DAG data models, parser, and validator for workflow definitions.

A workflow's dag_config JSON is parsed into WorkflowDag + DagNode objects
before the orchestrator touches them.  All structural validation (unknown
references, cycles, missing required fields) happens here so the orchestrator
receives a fully-trusted graph.
"""

from __future__ import annotations

import ast as _ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ─── Enumerations ─────────────────────────────────────────────────────────────


class NodeType(str, Enum):
    AGENT = "agent"
    CONDITION = "condition"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ─── Core data structures ─────────────────────────────────────────────────────


@dataclass
class DagNode:
    id: str
    type: NodeType
    depends_on: List[str] = field(default_factory=list)

    # agent-node fields
    agent_id: Optional[str] = None
    timeout_s: float = 60.0
    config: Dict[str, Any] = field(default_factory=dict)

    # condition-node fields
    condition: Optional[str] = None
    true_branch: Optional[str] = None
    false_branch: Optional[str] = None

    def validate_self(self) -> None:
        if self.type == NodeType.AGENT and not self.agent_id:
            raise ValueError(f"Agent node '{self.id}' must have an agent_id")
        if self.type == NodeType.CONDITION:
            if not self.condition:
                raise ValueError(f"Condition node '{self.id}' must have a 'condition' expression")
            try:
                _ast.parse(self.condition, mode="eval")
            except SyntaxError as exc:
                raise ValueError(
                    f"Condition node '{self.id}' has invalid expression: {exc}"
                ) from exc


@dataclass
class WorkflowDag:
    id: str
    name: str
    nodes: Dict[str, DagNode]  # node_id → DagNode

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Raise ValueError for any structural problem in the DAG."""
        for node in self.nodes.values():
            node.validate_self()
        self._check_refs()
        self._check_cycles()

    def _check_refs(self) -> None:
        """All node IDs referenced anywhere must exist."""
        node_ids: Set[str] = set(self.nodes.keys())
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in node_ids:
                    raise ValueError(
                        f"Node '{node.id}' depends_on unknown node '{dep}'"
                    )
            if node.type == NodeType.CONDITION:
                for branch_attr in ("true_branch", "false_branch"):
                    branch_id = getattr(node, branch_attr)
                    if branch_id and branch_id not in node_ids:
                        raise ValueError(
                            f"Condition node '{node.id}' references unknown "
                            f"{branch_attr} '{branch_id}'"
                        )

    def _check_cycles(self) -> None:
        """DFS-based cycle detection (colour-marking algorithm)."""
        WHITE, GRAY, BLACK = 0, 1, 2
        colour = {nid: WHITE for nid in self.nodes}

        def dfs(nid: str) -> None:
            colour[nid] = GRAY
            for dep in self.nodes[nid].depends_on:
                if colour[dep] == GRAY:
                    raise ValueError(
                        f"DAG contains a cycle: '{dep}' ↔ '{nid}'"
                    )
                if colour[dep] == WHITE:
                    dfs(dep)
            colour[nid] = BLACK

        for nid in self.nodes:
            if colour[nid] == WHITE:
                dfs(nid)

    # ── Scheduling helpers ────────────────────────────────────────────────────

    def get_ready_nodes(
        self,
        resolved: Set[str],   # completed | skipped
        in_flight: Set[str],  # currently executing
    ) -> List[str]:
        """
        Return nodes that are ready to run:
          – All their depends_on entries are in *resolved*.
          – They are not yet resolved or in-flight.
        """
        excluded = resolved | in_flight
        return [
            nid
            for nid, node in self.nodes.items()
            if nid not in excluded
            and all(dep in resolved for dep in node.depends_on)
        ]

    def execution_levels(self) -> List[List[str]]:
        """
        Return nodes grouped into dependency levels via Kahn's algorithm.
        Level 0 has no dependencies; level k depends only on levels < k.
        Used for static analysis and test assertions, not for live execution.
        """
        in_degree: Dict[str, int] = {nid: 0 for nid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                in_degree[node.id] += 1

        levels: List[List[str]] = []
        frontier = [nid for nid, d in in_degree.items() if d == 0]

        while frontier:
            levels.append(sorted(frontier))
            next_frontier: List[str] = []
            for nid in frontier:
                for other_id, other_node in self.nodes.items():
                    if nid in other_node.depends_on:
                        in_degree[other_id] -= 1
                        if in_degree[other_id] == 0:
                            next_frontier.append(other_id)
            frontier = next_frontier

        return levels


# ─── Parser ───────────────────────────────────────────────────────────────────


def parse_dag(raw: Dict[str, Any], fallback_id: str = "") -> WorkflowDag:
    """
    Parse a workflow's dag_config dict into a validated WorkflowDag.

    Raises ValueError for any structural or semantic problem.

    Expected format::

        {
          "id": "optional_id",
          "name": "optional_name",
          "nodes": [
            {"id": "step_a", "type": "agent", "agent_id": "...", "depends_on": []},
            {"id": "check",  "type": "condition", "condition": "output.score > 0.8",
             "depends_on": ["step_a"], "true_branch": "send", "false_branch": "queue"},
            ...
          ]
        }
    """
    if not raw:
        raise ValueError("dag_config is empty")

    raw_nodes = raw.get("nodes", [])
    if not raw_nodes:
        raise ValueError("dag_config has no nodes")

    nodes: Dict[str, DagNode] = {}
    for rn in raw_nodes:
        try:
            node_id = rn["id"]
        except KeyError:
            raise ValueError(f"Every node must have an 'id' field; got: {rn!r}")

        if node_id in nodes:
            raise ValueError(f"Duplicate node id '{node_id}'")

        try:
            node_type = NodeType(rn.get("type", "agent"))
        except ValueError:
            raise ValueError(
                f"Node '{node_id}' has unknown type '{rn.get('type')}'. "
                f"Valid types: {[t.value for t in NodeType]}"
            )

        nodes[node_id] = DagNode(
            id=node_id,
            type=node_type,
            depends_on=list(rn.get("depends_on", [])),
            agent_id=rn.get("agent_id"),
            timeout_s=float(rn.get("timeout_s", 60.0)),
            config=dict(rn.get("config", {})),
            condition=rn.get("condition"),
            true_branch=rn.get("true_branch"),
            false_branch=rn.get("false_branch"),
        )

    dag = WorkflowDag(
        id=raw.get("id", fallback_id),
        name=raw.get("name", ""),
        nodes=nodes,
    )
    dag.validate()
    return dag
