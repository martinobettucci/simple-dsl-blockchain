"""Mesh peer gossip: merge_peers unions endpoints, excludes self, and lets
knowledge propagate (A knows B, B knows C -> A learns C)."""

import pytest

from blockchain_demo.network import merge_peers, PeerInfo

pytestmark = pytest.mark.p0


def _ports(peers):
    return sorted(p.port for p in peers)


def test_merge_unions_and_excludes_self():
    local = [PeerInfo("127.0.0.1", 9001)]
    remote = [{"host": "127.0.0.1", "port": 9002},
              {"host": "127.0.0.1", "port": 9001},   # already known
              {"host": "127.0.0.1", "port": 9000}]   # this node itself
    merged = merge_peers(local, remote, self_port=9000)
    assert _ports(merged) == [9001, 9002]            # self (9000) excluded, no dup


def test_merge_ignores_malformed_entries():
    merged = merge_peers([], [{"host": "127.0.0.1"}, {"port": 9002}, {}], self_port=1)
    assert merged == []


def test_knowledge_propagates_one_hop():
    # A knows B; B knows C.  After A gossips B's peer list, A learns C.
    a = [PeerInfo("127.0.0.1", 9102)]                # A's view: knows B(9102)
    b_view = [{"host": "127.0.0.1", "port": 9103}]   # B advertises C(9103)
    a = merge_peers(a, b_view, self_port=9101)
    assert _ports(a) == [9102, 9103]
