// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Script, console} from "forge-std/Script.sol";
import {ZKNOX_dilithium65} from "ETHDILITHIUM/ZKNOX_dilithium65.sol";

/// Deploys the shared, per-chain half of on-chain execution: the Keccak-f[1600] helper and
/// ZKNox's ML-DSA-65 verifier. Every Q-Vault treasury on the chain then points at this verifier.
///
/// Dry run first (simulates against the live chain, sends nothing):
///     forge script script/DeployVerifier.s.sol --rpc-url $SEPOLIA_RPC_URL
///
/// Then for real, with the verifier's source published on Etherscan:
///     forge script script/DeployVerifier.s.sol --rpc-url $SEPOLIA_RPC_URL \
///         --private-key $EXECUTOR_PRIVATE_KEY --broadcast --verify --etherscan-api-key $ETHERSCAN_API_KEY
///
/// **This script records nothing.** Anything written from inside a forge script runs during local
/// simulation, before a single transaction is sent, so it would name contracts that may never
/// exist if the broadcast then fails (review finding 4). The addresses are recorded afterwards by
/// scripts/record_deployment.py (Phase 3), from confirmed receipts and the code actually on chain.
///
/// The helper is raw bytecode from fireblocks-labs/evm-ml-dsa-verifier, vendored by ZKNox, so it
/// has no Solidity source to verify. It does not need one: the verifier refuses to deploy against
/// (and re-checks on every call) any helper whose code hash is not the one below.
contract DeployVerifier is Script {
    string internal constant F1600_HEX = "lib/ETHDILITHIUM/test/f1600_170.hex";
    bytes32 internal constant F1600_CODEHASH = 0x4afb4435879cdf8e50474c7aab2bc3a679caed432550ad6dba64f509309a817b;

    function run() external returns (address helper, address verifier) {
        bytes memory runtime = vm.parseBytes(string.concat("0x", vm.readFile(F1600_HEX)));
        bytes memory initCode = abi.encodePacked(hex"61", uint16(runtime.length), hex"8061000b5f395ff3", runtime);

        vm.startBroadcast();
        assembly {
            helper := create(0, add(initCode, 32), mload(initCode))
        }
        require(helper != address(0), "F1600 helper: CREATE failed");
        require(helper.codehash == F1600_CODEHASH, "F1600 helper: unexpected code hash");
        verifier = address(new ZKNOX_dilithium65(helper));
        vm.stopBroadcast();

        console.log("F1600 helper:      ", helper);
        console.log("ML-DSA-65 verifier:", verifier);
        console.log("verifier runtime bytes:", verifier.code.length);
    }
}
