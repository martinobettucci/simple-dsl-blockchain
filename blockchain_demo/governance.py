"""On-chain governance: validator set + protocol config derived from the chain.

Everything except the initial validator set and bootstrap config (embedded in
the genesis block) is *derived* per node by folding governance transactions over
the chain.  The fold is a pure function so every node computes the same state.

Timing rule: the governance snapshot of block ``h-1`` (the parent) governs block
``h`` — i.e. who may sign it, the quorum, the PoW difficulty and the active
config.  Block ``h``'s own governance transactions produce ``G_h``, which governs
block ``h+1`` ("changes take effect next block").  This makes signing/finalizing
free of circular dependencies.

The derived snapshot is stored on each block but excluded from its identity hash
(like ``balances``) and re-derived/verified on receipt.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Set

from .block import calc_quorum
from .config import GOVERNABLE_KEYS

GOV_TX_TYPES = {"validator_apply", "validator_vote", "config_propose", "config_vote"}


@dataclass
class GovernanceState:
    validators: List[str]
    config: Dict[str, object]
    applications: Dict[str, Set[str]] = field(default_factory=dict)        # candidate -> voters
    config_proposals: Dict[str, dict] = field(default_factory=dict)        # pid -> {changes, votes:set}
    miss_counts: Dict[str, int] = field(default_factory=dict)
    last_signed_height: Dict[str, int] = field(default_factory=dict)

    def copy(self) -> "GovernanceState":
        return GovernanceState(
            validators=list(self.validators),
            config=dict(self.config),
            applications={k: set(v) for k, v in self.applications.items()},
            config_proposals={k: {"changes": dict(p["changes"]), "votes": set(p["votes"])}
                              for k, p in self.config_proposals.items()},
            miss_counts=dict(self.miss_counts),
            last_signed_height=dict(self.last_signed_height),
        )

    def to_snapshot(self) -> Dict:
        """Deterministic, JSON-serializable snapshot (sets -> sorted lists)."""
        return {
            "validators": sorted(self.validators),
            "config": dict(self.config),
            "quorum": quorum_at(self),
            "applications": {c: sorted(v) for c, v in sorted(self.applications.items())},
            "config_proposals": {pid: {"changes": dict(p["changes"]), "votes": sorted(p["votes"])}
                                 for pid, p in sorted(self.config_proposals.items())},
            "miss_counts": {k: self.miss_counts[k] for k in sorted(self.miss_counts)},
            "last_signed_height": {k: self.last_signed_height[k] for k in sorted(self.last_signed_height)},
        }

    @classmethod
    def from_snapshot(cls, d: Dict) -> "GovernanceState":
        return cls(
            validators=sorted(d.get("validators", [])),
            config=dict(d.get("config", {})),
            applications={c: set(v) for c, v in d.get("applications", {}).items()},
            config_proposals={pid: {"changes": dict(p.get("changes", {})), "votes": set(p.get("votes", []))}
                              for pid, p in d.get("config_proposals", {}).items()},
            miss_counts=dict(d.get("miss_counts", {})),
            last_signed_height=dict(d.get("last_signed_height", {})),
        )


def quorum_at(gs: GovernanceState) -> int:
    return calc_quorum(len(gs.validators), int(gs.config["QUORUM_PERCENT"]))


def active_validators(gs: GovernanceState) -> List[str]:
    return list(gs.validators)


def active_config(gs: GovernanceState) -> Dict[str, object]:
    return dict(gs.config)


def genesis_state(genesis_block) -> GovernanceState:
    """Build G_0 from the genesis block's embedded governance snapshot."""
    return GovernanceState.from_snapshot(genesis_block.governance)


def apply_block(parent_gs: GovernanceState, block, *, height: int) -> GovernanceState:
    """Pure fold: G_{h-1} + block(height h) -> G_h.

    Order is consensus-critical: liveness -> apply govtxs -> resolve admissions
    -> resolve config -> resolve removals.
    """
    gs = parent_gs.copy()
    parent_set = set(parent_gs.validators)
    q = quorum_at(parent_gs)  # quorum is measured against the PARENT validator set

    # 1) Liveness: charge/credit only the validators in force for this block.
    frozen = set(block.signers_frozen)
    for v in parent_gs.validators:
        if v in frozen:
            gs.last_signed_height[v] = height
        else:
            gs.miss_counts[v] = gs.miss_counts.get(v, 0) + 1

    # 2) Apply governance transactions in block order.
    for tx in block.transactions:
        t = tx.type
        if t == "validator_apply":
            cand = tx.from_addr
            if cand not in gs.validators:
                gs.applications.setdefault(cand, set())
        elif t == "validator_vote":
            cand = tx.data.get("candidate")
            if tx.from_addr in parent_set and cand in gs.applications:
                gs.applications[cand].add(tx.from_addr)
        elif t == "config_propose":
            if tx.from_addr in parent_set:
                changes = {k: v for k, v in tx.data.get("changes", {}).items() if k in GOVERNABLE_KEYS}
                if changes:
                    gs.config_proposals[tx.hash()] = {"changes": changes, "votes": {tx.from_addr}}
        elif t == "config_vote":
            pid = tx.data.get("pid")
            if tx.from_addr in parent_set and pid in gs.config_proposals:
                gs.config_proposals[pid]["votes"].add(tx.from_addr)
        # "dsl" and unknown types are ignored by governance

    # 3) Admissions: candidate approved by a quorum of the parent set.
    for cand in sorted(gs.applications):
        if len(gs.applications[cand] & parent_set) >= q:
            if cand not in gs.validators:
                gs.validators.append(cand)
                gs.last_signed_height[cand] = height   # admitted-this-block: exempt from miss/removal
                gs.miss_counts[cand] = 0
            del gs.applications[cand]
    gs.validators.sort()

    # 4) Config proposals approved by a quorum of the parent set.
    for pid in sorted(gs.config_proposals):
        if len(gs.config_proposals[pid]["votes"] & parent_set) >= q:
            gs.config.update(gs.config_proposals[pid]["changes"])
            del gs.config_proposals[pid]

    # 5) Automatic removals (deterministic, with a safety floor).
    n = int(gs.config["LIVENESS_OFFLINE_N"])
    x = int(gs.config["LIVENESS_MISS_X"])
    floor = int(gs.config["VALIDATOR_FLOOR"])
    removable = sorted(
        v for v in gs.validators
        if (height - gs.last_signed_height.get(v, height) > n) or (gs.miss_counts.get(v, 0) >= x)
    )
    for v in removable:
        if len(gs.validators) <= floor:
            break
        gs.validators.remove(v)
        gs.miss_counts.pop(v, None)
        gs.last_signed_height.pop(v, None)

    return gs


def fold_chain(chain: List, genesis_block=None) -> List[GovernanceState]:
    """Return [G_0, G_1, ..., G_tip] aligned with ``chain`` (chain[0] is genesis)."""
    if not chain:
        return []
    states = [genesis_state(chain[0])]
    for blk in chain[1:]:
        states.append(apply_block(states[-1], blk, height=blk.header.height))
    return states
