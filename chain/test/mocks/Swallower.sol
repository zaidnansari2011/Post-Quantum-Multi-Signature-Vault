// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// A call target that catches its own failure: `run` succeeds whether or not `work` did.
/// Against such a target, a submitter who could choose the call's gas could make `work` run out
/// and still have the decision recorded as executed. This mock is how the tests prove they cannot.
contract Swallower {
    bool public done;

    function run() external {
        try this.work() {
            done = true;
        } catch {}
    }

    function work() external pure returns (uint256 acc) {
        for (uint256 i = 0; i < 5_000; i++) {
            acc += i;
        }
    }
}
