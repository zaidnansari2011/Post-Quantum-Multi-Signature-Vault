"""A Sepolia node whose stand-in treasury answers ``configNonce()`` (plan D43).

Approving a payment asks the chain which configuration the treasury is at, and refuses when it
cannot. Tests that approve payments against the stand-in treasury rows of
``test_payment_decisions`` install this: the node answers for that one address, the relayer in
``app.extensions`` reaches it, and a test moves ``nonce`` (or stops the answers) to play the chain.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import encode
from fake_ethereum import Call, FakeNode, Outcome

from qvault.chain.relayer import Relayer
from qvault.chain.rpc import EthRpc
from qvault.chain.treasury_check import VIEWS

SEPOLIA = 11_155_111


@dataclass
class ChainNonce:
    node: FakeNode
    relayer: Relayer
    nonce: int = 0
    answering: bool = True

    def answer(self, call: Call) -> Outcome:
        if not self.answering or call.data[:4] != VIEWS["configNonce"]:
            return Outcome(False, b"", 30_000)
        return Outcome(True, encode(["uint256"], [self.nonce]), 30_000)


def install(app, treasury: str) -> ChainNonce:
    node = FakeNode()
    relayer = Relayer(EthRpc(node.transport), "0x" + "11" * 32, chain_id=SEPOLIA)
    chain = ChainNonce(node, relayer)
    node.on(treasury, chain.answer)
    app.extensions["relayer"] = relayer
    return chain
