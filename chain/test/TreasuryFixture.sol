// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {ZKNOX_dilithium65} from "ETHDILITHIUM/ZKNOX_dilithium65.sol";
import {QVaultTreasury} from "../src/QVaultTreasury.sol";
import {PingTarget} from "./mocks/PingTarget.sol";
import {Reenterer} from "./mocks/Reenterer.sol";
import {Swallower} from "./mocks/Swallower.sol";

/// Deploys the world described by test/fixtures/treasury.json at exactly the addresses it names.
///
/// The fixture's digests bind the treasury address and chain id, and its signer identities bind
/// the verifier's key pointers, so everything is placed deterministically: contracts with
/// deployCodeTo, the chain id with vm.chainId, and the verifier's CREATE nonce with setNonceUnsafe.
/// setUp then asserts that each key landed where Python predicted before any test runs, so a
/// drift between the two shows up as one clear failure here instead of every signature check
/// failing for no visible reason.
///
/// Predicting pointer addresses is a test device. Production code must read them back from a
/// confirmed setKey instead, because anyone can call setKey first (plan D17).
///
/// Memory: every vm.readFile copies the whole file into EVM memory, and memory is not reclaimed
/// within a call. So each helper reads the file at most once, and the per-key values tests use
/// constantly are cached in storage during setUp.
abstract contract TreasuryFixture is Test {
    string internal constant FIXTURE = "test/fixtures/treasury.json";
    string internal constant KEY_BLOBS = "test/fixtures/treasury_key_blobs.json";
    string internal constant F1600_HEX = "lib/ETHDILITHIUM/test/f1600_170.hex";
    bytes32 internal constant F1600_CODEHASH = 0x4afb4435879cdf8e50474c7aab2bc3a679caed432550ad6dba64f509309a817b;

    ZKNOX_dilithium65 internal verifier;
    QVaultTreasury internal treasury;
    PingTarget internal target;
    Reenterer internal reenterer;
    Swallower internal swallower;
    address internal recipient;
    address internal gasProbe;

    bytes[] internal signerOf;
    bytes[] internal handleOf;
    bytes[] internal pointersOf;
    bytes32[] internal keyIdOf;

    function setUp() public virtual {
        string memory json = _json();
        vm.chainId(vm.parseJsonUint(json, ".chain_id"));

        address helper = _deployF1600Helper();
        address v = vm.parseJsonAddress(json, ".verifier");
        deployCodeTo("ZKNOX_dilithium65.sol:ZKNOX_dilithium65", abi.encode(helper), v);
        verifier = ZKNOX_dilithium65(v);
        vm.setNonceUnsafe(v, uint64(vm.parseJsonUint(json, ".verifier_first_nonce")));

        bytes[] memory blobs = vm.parseJsonBytesArray(vm.readFile(KEY_BLOBS), ".blobs");
        uint256 keyCount = vm.parseJsonUint(json, ".key_count");
        assertEq(blobs.length, keyCount, "one blob per key");
        for (uint256 i = 0; i < keyCount; i++) {
            bytes memory pointers = verifier.setKey(blobs[i]);
            assertEq(pointers, vm.parseJsonBytes(json, _key(i, "pointers")), "key pointers != Python's prediction");

            bytes memory handle = vm.parseJsonBytes(json, _key(i, "handle"));
            bytes memory signer = vm.parseJsonBytes(json, _key(i, "signer"));
            assertEq(abi.encodePacked(v, handle), signer, "signer != verifier || handle");
            signerOf.push(signer);
            handleOf.push(handle);
            pointersOf.push(pointers);
            // Python's keccak256(SHAKE256(pk, 64)); test_KeyIdsMatchPython checks the contract agrees.
            keyIdOf.push(vm.parseJsonBytes32(json, _key(i, "key_id")));
        }
        // Key 0's content, stored a second time under fresh pointers (the duplicate-key case).
        bytes memory again = verifier.setKey(blobs[0]);
        assertEq(again, vm.parseJsonBytes(json, ".duplicate_of_key0.pointers"), "duplicate pointers");

        uint256[] memory initial = vm.parseJsonUintArray(json, ".initial.signers");
        uint64 initialThreshold = uint64(vm.parseJsonUint(json, ".initial.threshold"));
        treasury = _deployTreasury(vm.parseJsonAddress(json, ".treasury"), _signersFor(initial), initialThreshold);
        vm.deal(address(treasury), 1 ether);

        deployCodeTo("PingTarget.sol:PingTarget", vm.parseJsonAddress(json, ".target"));
        target = PingTarget(vm.parseJsonAddress(json, ".target"));
        deployCodeTo("Reenterer.sol:Reenterer", vm.parseJsonAddress(json, ".reenterer"));
        reenterer = Reenterer(vm.parseJsonAddress(json, ".reenterer"));
        deployCodeTo("Swallower.sol:Swallower", vm.parseJsonAddress(json, ".swallower"));
        swallower = Swallower(vm.parseJsonAddress(json, ".swallower"));
        recipient = vm.parseJsonAddress(json, ".recipient");
        gasProbe = vm.parseJsonAddress(json, ".gas_probe");
        vm.etch(gasProbe, hex"5a5f5500"); // GAS PUSH0 SSTORE STOP: slot 0 = gas left on entry
    }

    // --- fixture access ----------------------------------------------------------------------

    function _json() internal view returns (string memory) {
        return vm.readFile(FIXTURE);
    }

    function _key(uint256 i, string memory field) internal pure returns (string memory) {
        return string.concat(".keys[", vm.toString(i), "].", field);
    }

    function _signer(uint256 i) internal view returns (bytes memory) {
        return signerOf[i];
    }

    function _handle(uint256 i) internal view returns (bytes memory) {
        return handleOf[i];
    }

    function _pointers(uint256 i) internal view returns (bytes memory) {
        return pointersOf[i];
    }

    function _keyId(uint256 i) internal view returns (bytes32) {
        return keyIdOf[i];
    }

    function _signersFor(uint256[] memory keys) internal view returns (bytes[] memory signers) {
        signers = new bytes[](keys.length);
        for (uint256 i = 0; i < keys.length; i++) {
            signers[i] = signerOf[keys[i]];
        }
    }

    function _initialSigners() internal view returns (bytes[] memory) {
        return _signersFor(_keys(0, 1, 2));
    }

    function _initialThreshold() internal pure returns (uint64) {
        return 2;
    }

    function _deployTreasury(address at, bytes[] memory signers, uint64 threshold_)
        internal
        returns (QVaultTreasury)
    {
        deployCodeTo("QVaultTreasury.sol:QVaultTreasury", abi.encode(address(verifier), signers, threshold_), at);
        return QVaultTreasury(payable(at));
    }

    /// An execution scenario's call fields.
    struct Call {
        bytes32 proposalId;
        address to;
        uint256 value;
        bytes data;
        uint64 callGas;
        uint64 validUntil;
        bytes32 digest;
    }

    function _call(string memory scenario) internal view returns (Call memory c) {
        string memory json = _json();
        string memory p = string.concat(".", scenario, ".");
        c.proposalId = vm.parseJsonBytes32(json, string.concat(p, "proposal_id"));
        c.to = vm.parseJsonAddress(json, string.concat(p, "to"));
        c.value = vm.parseJsonUint(json, string.concat(p, "value"));
        c.data = vm.parseJsonBytes(json, string.concat(p, "data"));
        c.callGas = uint64(vm.parseJsonUint(json, string.concat(p, "call_gas")));
        c.validUntil = uint64(vm.parseJsonUint(json, string.concat(p, "valid_until")));
        c.digest = vm.parseJsonBytes32(json, string.concat(p, "digest"));
    }

    /// A reconfiguration scenario's fields.
    struct Change {
        uint256 nonce;
        bytes[] add;
        bytes[] remove;
        uint64 threshold;
        uint64 validUntil;
        bytes32 digest;
    }

    function _change(string memory scenario) internal view returns (Change memory c) {
        string memory json = _json();
        string memory p = string.concat(".", scenario, ".");
        c.nonce = vm.parseJsonUint(json, string.concat(p, "nonce"));
        c.add = vm.parseJsonBytesArray(json, string.concat(p, "add"));
        c.remove = vm.parseJsonBytesArray(json, string.concat(p, "remove"));
        c.threshold = uint64(vm.parseJsonUint(json, string.concat(p, "threshold")));
        c.validUntil = uint64(vm.parseJsonUint(json, string.concat(p, "valid_until")));
        c.digest = vm.parseJsonBytes32(json, string.concat(p, "digest"));
    }

    /// The signature a scenario holds from key `keyIndex`.
    function _sig(string memory scenario, uint256 keyIndex) internal view returns (bytes memory) {
        return _sigFrom(_json(), scenario, keyIndex);
    }

    function _sigFrom(string memory json, string memory scenario, uint256 keyIndex)
        internal
        pure
        returns (bytes memory)
    {
        uint256[] memory who = vm.parseJsonUintArray(json, string.concat(".", scenario, ".signers"));
        for (uint256 i = 0; i < who.length; i++) {
            if (who[i] == keyIndex) {
                return vm.parseJsonBytes(json, string.concat(".", scenario, ".signatures[", vm.toString(i), "]"));
            }
        }
        revert(string.concat("fixture has no signature from key ", vm.toString(keyIndex), " in ", scenario));
    }

    /// abi.encode(signers, signatures) for the given keys, in the order given.
    function _multisig(string memory scenario, uint256[] memory keys) internal view returns (bytes memory) {
        string memory json = _json();
        bytes[] memory signers = new bytes[](keys.length);
        bytes[] memory signatures = new bytes[](keys.length);
        for (uint256 i = 0; i < keys.length; i++) {
            signers[i] = signerOf[keys[i]];
            signatures[i] = _sigFrom(json, scenario, keys[i]);
        }
        return abi.encode(signers, signatures);
    }

    function _keys(uint256 a) internal pure returns (uint256[] memory k) {
        k = new uint256[](1);
        k[0] = a;
    }

    function _keys(uint256 a, uint256 b) internal pure returns (uint256[] memory k) {
        k = new uint256[](2);
        (k[0], k[1]) = (a, b);
    }

    function _keys(uint256 a, uint256 b, uint256 c) internal pure returns (uint256[] memory k) {
        k = new uint256[](3);
        (k[0], k[1], k[2]) = (a, b, c);
    }

    function _keysUpTo(uint256 n) internal pure returns (uint256[] memory k) {
        k = new uint256[](n);
        for (uint256 i = 0; i < n; i++) {
            k[i] = i;
        }
    }

    // --- helpers -----------------------------------------------------------------------------

    /// Key i's expanded blob. Reads the ~650 KB blobs file, so call it at most once per test.
    function _blob(uint256 i) internal view returns (bytes memory) {
        return vm.parseJsonBytesArray(vm.readFile(KEY_BLOBS), ".blobs")[i];
    }

    function _slice(bytes memory b, uint256 start, uint256 len) internal pure returns (bytes memory out) {
        require(start + len <= b.length, "slice out of range");
        out = new bytes(len);
        assembly ("memory-safe") {
            mcopy(add(out, 32), add(add(b, 32), start), len)
        }
    }

    function _word(bytes memory b, uint256 at) internal pure returns (bytes32 w) {
        require(at + 32 <= b.length, "word out of range");
        assembly ("memory-safe") {
            w := mload(add(add(b, 32), at))
        }
    }

    /// The i-th address (0 or 1) in a 40-byte key handle.
    function _pointerAt(bytes memory handle, uint256 i) internal pure returns (address a) {
        require(handle.length >= 40 && i < 2, "not a key handle");
        assembly ("memory-safe") {
            a := shr(96, mload(add(add(handle, 32), mul(i, 20))))
        }
    }

    function _deployF1600Helper() internal returns (address helper) {
        bytes memory runtime = vm.parseBytes(string.concat("0x", vm.readFile(F1600_HEX)));
        // PUSH2 len, DUP1, PUSH2 0x000b, PUSH0, CODECOPY, PUSH0, RETURN, then the runtime.
        bytes memory initCode = abi.encodePacked(hex"61", uint16(runtime.length), hex"8061000b5f395ff3", runtime);
        assembly {
            helper := create(0, add(initCode, 32), mload(initCode))
        }
        require(helper != address(0), "F1600 helper: CREATE failed");
        require(helper.codehash == F1600_CODEHASH, "F1600 helper: unexpected code hash");
    }

    function _executeCalldata(string memory scenario, uint256[] memory keys) internal view returns (bytes memory) {
        Call memory c = _call(scenario);
        return abi.encodeCall(
            QVaultTreasury.execute,
            (c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, _multisig(scenario, keys))
        );
    }

    function _execute(string memory scenario, uint256[] memory keys) internal returns (bytes memory) {
        Call memory c = _call(scenario);
        return treasury.execute(
            c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, _multisig(scenario, keys)
        );
    }

    function _reconfigure(string memory scenario, uint256[] memory keys) internal {
        Change memory c = _change(scenario);
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, _multisig(scenario, keys));
    }

    /// Gas a transaction carrying `data` pays before execution: EIP-2028 calldata pricing, or the
    /// EIP-7623 floor when that is higher. Used to judge a call against the per-transaction cap.
    function _txGas(uint256 executionGas, bytes memory data) internal pure returns (uint256) {
        uint256 zeros;
        for (uint256 i = 0; i < data.length; i++) {
            if (data[i] == 0) zeros++;
        }
        uint256 nonZeros = data.length - zeros;
        uint256 standard = 21_000 + zeros * 4 + nonZeros * 16 + executionGas;
        uint256 floor = 21_000 + (zeros + nonZeros * 4) * 10;
        return standard > floor ? standard : floor;
    }
}
