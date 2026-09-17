// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// A malicious call target: when the treasury calls attack(), it calls straight back into the
/// treasury with a pre-armed payload (a genuinely approved execution) and bubbles up any revert.
contract Reenterer {
    address public treasury;
    bytes public armed;

    function arm(address treasury_, bytes calldata payload) external {
        treasury = treasury_;
        armed = payload;
    }

    function attack() external {
        (bool ok, bytes memory ret) = treasury.call(armed);
        if (!ok) {
            assembly {
                revert(add(ret, 32), mload(ret))
            }
        }
    }
}
