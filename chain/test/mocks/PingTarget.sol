// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// A call target that records what the treasury sent it, and can be told to fail.
contract PingTarget {
    uint256 public lastValue;
    uint256 public lastArg;
    address public lastCaller;
    bool public fail;

    error Refused();

    function setFail(bool fail_) external {
        fail = fail_;
    }

    function ping(uint256 arg) external payable {
        if (fail) revert Refused();
        lastValue = msg.value;
        lastArg = arg;
        lastCaller = msg.sender;
    }
}
