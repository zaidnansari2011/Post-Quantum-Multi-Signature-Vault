// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {console} from "forge-std/Test.sol";
import {MultiSignerERC7913} from "@openzeppelin/contracts/utils/cryptography/signers/MultiSignerERC7913.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";
import {ISigVerifier} from "InterfaceVerifier/IVerifier.sol";
import {QVaultTreasury, VerifierBound} from "../src/QVaultTreasury.sol";
import {PingTarget} from "./mocks/PingTarget.sol";
import {TreasuryFixture} from "./TreasuryFixture.sol";

/// Every signature in these tests was produced by Q-Vault's MLDSA65Provider (quantcrypt / PQClean)
/// in scripts/gen_chain_fixtures.py. Nothing here signs anything.
contract QVaultTreasuryTest is TreasuryFixture {
    uint256 internal constant TX_GAS_CAP = 16_777_216; // EIP-7825 per-transaction cap

    event Executed(bytes32 indexed proposalId, address indexed to, uint256 value, bytes32 dataHash);
    event Deposited(address indexed from, uint256 value);

    // --- 1. Python and Solidity agree ----------------------------------------------------------

    function test_ConstantsMatchPython() public view {
        string memory json = _json();
        assertEq(treasury.EXECUTE_TAG(), vm.parseJsonBytes32(json, ".tags.execute"));
        assertEq(treasury.RECONFIGURE_TAG(), vm.parseJsonBytes32(json, ".tags.reconfigure"));
        assertEq(uint256(treasury.MAX_THRESHOLD()), vm.parseJsonUint(json, ".max_threshold"));
        assertEq(treasury.SIGNER_BYTES(), _signer(0).length);
    }

    function test_ExecutionDigestsMatchPython() public view {
        string[8] memory scenarios = [
            "execute_eth",
            "execute_call",
            "execute_reentrant",
            "execute_swallow",
            "execute_gas_probe",
            "execute_after_rotate",
            "execute_three",
            "execute_max"
        ];
        for (uint256 i = 0; i < scenarios.length; i++) {
            Call memory c = _call(scenarios[i]);
            assertEq(
                treasury.executionDigest(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil),
                c.digest,
                scenarios[i]
            );
        }
    }

    function test_ReconfigureDigestsMatchPython() public view {
        string[11] memory scenarios = [
            "reconfigure_rotate",
            "reconfigure_raise",
            "reconfigure_lower",
            "reconfigure_max",
            "reconfigure_too_high",
            "reconfigure_foreign",
            "reconfigure_duplicate",
            "reconfigure_mismatch",
            "reconfigure_unreachable",
            "reconfigure_remove_nonmember",
            "reconfigure_move_key"
        ];
        for (uint256 i = 0; i < scenarios.length; i++) {
            Change memory c = _change(scenarios[i]);
            assertEq(
                treasury.reconfigureDigest(c.nonce, c.add, c.remove, c.threshold, c.validUntil), c.digest, scenarios[i]
            );
        }
    }

    function test_KeyIdsMatchPython() public view {
        // The contract reads tr out of each key's stored half 0; Python computes SHAKE256(pk, 64).
        for (uint256 k = 0; k < 3; k++) {
            assertTrue(treasury.keyInUse(_keyId(k)), "initial signer's key id");
        }
        for (uint256 k = 3; k < 8; k++) {
            assertFalse(treasury.keyInUse(_keyId(k)), "non-signer's key id");
        }
    }

    function test_QuantcryptSignaturesVerifyOnChain() public view {
        Call memory c = _call("execute_eth");
        for (uint256 k = 0; k < 3; k++) {
            assertEq(verifier.verify(_handle(k), c.digest, _sig("execute_eth", k)), ISigVerifier.verify.selector);
        }
        // The same through the 40-byte handle alone: the verifier reads only the pointers, and the
        // code hashes the treasury appends (D17) cost it nothing and change nothing.
        assertEq(verifier.verify(_pointers(0), c.digest, _sig("execute_eth", 0)), ISigVerifier.verify.selector);
    }

    function test_OneVerificationGas() public view {
        Call memory c = _call("execute_eth");
        verifier.verify(_handle(0), c.digest, _sig("execute_eth", 0));
        console.log("ML-DSA-65 verification gas:", vm.lastCallGas().gasTotalUsed);
    }

    function test_TamperedSignatureFailsOnChain() public view {
        Call memory c = _call("execute_eth");
        bytes memory sig = _sig("execute_eth", 0);
        sig[1000] ^= 0x01;
        assertEq(verifier.verify(_handle(0), c.digest, sig), bytes4(0xFFFFFFFF));
        // and a valid signature under someone else's key
        assertEq(verifier.verify(_handle(1), c.digest, _sig("execute_eth", 0)), bytes4(0xFFFFFFFF));
    }

    // --- 2. executing an approved decision -----------------------------------------------------

    function test_TwoOfThreePaysOut() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        uint256 before = recipient.balance;

        vm.expectEmit(address(treasury));
        emit Executed(c.proposalId, c.to, c.value, keccak256(c.data));
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);

        uint256 gasUsed = vm.lastCallGas().gasTotalUsed;
        console.log("execute, 2 signatures, gas:", gasUsed);
        console.log("execute, 2 signatures, tx gas incl. calldata:", _txGas(gasUsed, _executeCalldata("execute_eth", _keys(0, 1))));
        assertEq(recipient.balance - before, c.value);
        assertTrue(treasury.executed(c.proposalId));
    }

    function test_ThreeSignaturesAlsoPayOut() public {
        _execute("execute_eth", _keys(0, 1, 2));
        console.log("execute, 3 signatures, gas:", vm.lastCallGas().gasTotalUsed);
        assertTrue(treasury.executed(_call("execute_eth").proposalId));
    }

    function test_SignerOrderDoesNotMatter() public {
        _execute("execute_eth", _keys(1, 0));
        assertTrue(treasury.executed(_call("execute_eth").proposalId));
    }

    function test_AnyoneMaySubmitAnApproval() public {
        // The submitter has no authority, so needs none: the signatures are the authorisation.
        bytes memory payload = _executeCalldata("execute_eth", _keys(0, 1));
        vm.prank(address(0xCAFE));
        (bool ok,) = address(treasury).call(payload);
        assertTrue(ok);
        assertTrue(treasury.executed(_call("execute_eth").proposalId));
    }

    function test_ReplayIsRejected() public {
        _execute("execute_eth", _keys(0, 1));
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 2)); // even a different pair
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.AlreadyExecuted.selector, c.proposalId));
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_ExpiredApprovalIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.warp(uint256(c.validUntil) + 1);
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.Expired.selector, c.validUntil));
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_ApprovalIsUsableOnItsLastSecond() public {
        vm.warp(uint256(_call("execute_eth").validUntil));
        _execute("execute_eth", _keys(0, 1));
        assertTrue(treasury.executed(_call("execute_eth").proposalId));
    }

    function test_ExtendingTheDeadlineIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil + 1, multisig);
    }

    function test_ChangedCallGasIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, 0, c.validUntil, multisig);
    }

    function test_OneSignatureIsBelowThreshold() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_SameSignerTwiceIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 0));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_EmptyAndMalformedMultisigAreRejected() public {
        Call memory c = _call("execute_eth");
        bytes[] memory bad = new bytes[](3);
        bad[0] = "";
        bad[1] = hex"00";
        bad[2] = abi.encode(new bytes[](0), new bytes[](0)); // well-formed, zero signers
        for (uint256 i = 0; i < bad.length; i++) {
            vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
            treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, bad[i]);
        }
    }

    function test_AnExtraInvalidSignatureSpoilsTheBatch() public {
        // Two valid signatures meet the threshold, but a third, tampered one is not ignored.
        Call memory c = _call("execute_eth");
        bytes[] memory signers = new bytes[](3);
        bytes[] memory sigs = new bytes[](3);
        for (uint256 k = 0; k < 3; k++) {
            signers[k] = _signer(k);
            sigs[k] = _sig("execute_eth", k);
        }
        sigs[2][500] ^= 0x04;
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, abi.encode(signers, sigs));
    }

    function test_TamperedSignatureIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes[] memory signers = new bytes[](2);
        bytes[] memory sigs = new bytes[](2);
        (signers[0], signers[1]) = (_signer(0), _signer(1));
        (sigs[0], sigs[1]) = (_sig("execute_eth", 0), _sig("execute_eth", 1));
        sigs[1][3000] ^= 0x80;
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, abi.encode(signers, sigs));
    }

    function test_SignatureAttributedToWrongSignerIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes[] memory signers = new bytes[](2);
        bytes[] memory sigs = new bytes[](2);
        (signers[0], signers[1]) = (_signer(0), _signer(1));
        (sigs[0], sigs[1]) = (_sig("execute_eth", 1), _sig("execute_eth", 0)); // swapped
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, abi.encode(signers, sigs));
    }

    function test_ChangedRecipientIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, address(0xA77AC4E2), c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_ChangedAmountIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value * 100, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_AddedCalldataIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, hex"00", c.callGas, c.validUntil, multisig);
    }

    function test_OtherProposalIdIsRejected() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(keccak256("another decision"), c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    /// Changing any ONE field the approvers signed invalidates the approval. One field per run, so
    /// dropping any single field from the digest makes some run fail (re-review finding 6).
    /// forge-config: default.fuzz.runs = 48
    function testFuzz_ChangingAnyOneExecutionFieldIsRejected(uint8 field, bytes32 random) public {
        Call memory c = _call("execute_eth");
        field = uint8(bound(field, 0, 5));
        if (field == 0) {
            vm.assume(random != c.proposalId);
            c.proposalId = random;
        } else if (field == 1) {
            vm.assume(address(uint160(uint256(random))) != c.to);
            c.to = address(uint160(uint256(random)));
        } else if (field == 2) {
            vm.assume(uint96(uint256(random)) != c.value);
            c.value = uint96(uint256(random));
        } else if (field == 3) {
            c.data = abi.encodePacked(random); // the approved call has none
        } else if (field == 4) {
            vm.assume(uint64(uint256(random)) != c.callGas);
            c.callGas = uint64(uint256(random));
        } else {
            uint64 later = uint64(bound(uint256(random), block.timestamp, type(uint64).max)); // not merely expired
            vm.assume(later != c.validUntil);
            c.validUntil = later;
        }
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_CallDataAboveTheCapIsRefused() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.CallDataTooLarge.selector, 4097, 4096));
        treasury.execute(c.proposalId, c.to, c.value, new bytes(4097), c.callGas, c.validUntil, multisig);
    }

    function test_SignaturesAreBoundToTheChain() public {
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.chainId(1); // the same contract state, replayed on another chain
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_SignaturesAreBoundToTheTreasury() public {
        // A second treasury with the very same signers cannot be drained with the first one's approvals.
        QVaultTreasury twin = _deployTreasury(address(0x7EA6), _initialSigners(), _initialThreshold());
        vm.deal(address(twin), 1 ether);
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        twin.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
    }

    function test_CallWithValueAndData() public {
        Call memory c = _call("execute_call");
        _execute("execute_call", _keys(0, 1));
        assertEq(target.lastArg(), 42);
        assertEq(target.lastValue(), c.value);
        assertEq(target.lastCaller(), address(treasury));
    }

    function test_FailedCallRevertsAndCanBeRetried() public {
        target.setFail(true);
        Call memory c = _call("execute_call");
        bytes memory multisig = _multisig("execute_call", _keys(0, 1));
        vm.expectRevert(
            abi.encodeWithSelector(QVaultTreasury.CallFailed.selector, abi.encodeWithSelector(PingTarget.Refused.selector))
        );
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
        assertFalse(treasury.executed(c.proposalId), "a failed call must not be recorded as executed");

        target.setFail(false);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
        assertTrue(treasury.executed(c.proposalId));
    }

    function test_UnfundedTreasuryCanRetryAfterFunding() public {
        vm.deal(address(treasury), 0);
        Call memory c = _call("execute_eth");
        bytes memory multisig = _multisig("execute_eth", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.CallFailed.selector, bytes("")));
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);

        vm.deal(address(treasury), 1 ether);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
        assertTrue(treasury.executed(c.proposalId));
    }

    function test_SubmitterCannotStarveTheCall() public {
        // Review finding 6: against a target that swallows its own failure, a low gas limit used to
        // leave the decision spent and the work undone. Now the contract refuses to start the call
        // unless it can forward the approved callGas in full.
        //
        // A HIGH-LEVEL call, deliberately. Under forge 1.7.1, expectPartialRevert before a low-level
        // .call only flips the returned bool and fails nothing, so the first version of this test
        // could not fail (re-review finding 1).
        Call memory c = _call("execute_swallow");
        bytes memory multisig = _multisig("execute_swallow", _keys(0, 1));

        vm.expectPartialRevert(QVaultTreasury.InsufficientGas.selector);
        treasury.execute{gas: 3_600_000}(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
        assertFalse(treasury.executed(c.proposalId), "a starved attempt must not spend the decision");
        assertFalse(swallower.done());

        treasury.execute{gas: 8_000_000}(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
        assertTrue(treasury.executed(c.proposalId));
        assertTrue(swallower.done(), "with the approved gas, the work completes");
    }

    function test_TheCallReceivesExactlyItsApprovedGas() public {
        // Find the lowest gas limit at which execute succeeds; then prove that at that limit the
        // callee got all of callGas, and one gas less is refused by the gas check itself rather
        // than by some starved step (re-review finding 1). The probe's code is GAS PUSH0 SSTORE
        // STOP, so slot 0 holds the gas it had on entry minus the 2 that GAS itself costs.
        Call memory c = _call("execute_gas_probe");
        bytes memory multisig = _multisig("execute_gas_probe", _keys(0, 1));
        uint256 lo = 3_000_000; // two signature checks alone need more
        uint256 hi = 8_000_000;
        while (hi - lo > 1) {
            uint256 mid = (lo + hi) / 2;
            uint256 snapshot = vm.snapshotState();
            bool ok;
            try treasury.execute{gas: mid}(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig) {
                ok = true;
            } catch {}
            vm.revertToState(snapshot);
            if (ok) hi = mid;
            else lo = mid;
        }
        console.log("lowest gas limit that executes (callGas 1,000,000):", hi);

        vm.expectPartialRevert(QVaultTreasury.InsufficientGas.selector);
        treasury.execute{gas: hi - 1}(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);

        treasury.execute{gas: hi}(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, multisig);
        assertEq(uint256(vm.load(gasProbe, 0)) + 2, c.callGas, "the callee received exactly callGas");
    }

    function test_ReentrantExecuteIsBlocked() public {
        // The reenterer holds a genuinely approved execution and tries to run it mid-call.
        reenterer.arm(address(treasury), _executeCalldata("execute_eth", _keys(0, 1)));
        Call memory outer = _call("execute_reentrant");
        bytes memory multisig = _multisig("execute_reentrant", _keys(0, 1));
        vm.expectRevert(
            abi.encodeWithSelector(
                QVaultTreasury.CallFailed.selector,
                abi.encodeWithSelector(ReentrancyGuardTransient.ReentrancyGuardReentrantCall.selector)
            )
        );
        treasury.execute(outer.proposalId, outer.to, outer.value, outer.data, outer.callGas, outer.validUntil, multisig);

        // Nothing was consumed: both decisions remain executable in the ordinary way.
        assertFalse(treasury.executed(outer.proposalId));
        assertFalse(treasury.executed(_call("execute_eth").proposalId));
        _execute("execute_eth", _keys(0, 1));
    }

    function test_DepositsAreAccepted() public {
        vm.deal(address(this), 1 ether);
        vm.expectEmit(address(treasury));
        emit Deposited(address(this), 0.25 ether);
        (bool ok,) = address(treasury).call{value: 0.25 ether}("");
        assertTrue(ok);
    }

    // --- 3. changing the signer set -------------------------------------------------------------

    function test_RotateASigner() public {
        _reconfigure("reconfigure_rotate", _keys(0, 1));
        console.log("reconfigure (rotate one signer) gas:", vm.lastCallGas().gasTotalUsed);

        assertTrue(treasury.isSigner(_signer(3)));
        assertFalse(treasury.isSigner(_signer(2)));
        assertTrue(treasury.keyInUse(_keyId(3)));
        assertFalse(treasury.keyInUse(_keyId(2)), "a removed key's content is released");
        assertEq(treasury.getSignerCount(), 3);
        assertEq(treasury.threshold(), 2);
        assertEq(treasury.configNonce(), 1);

        Call memory c = _call("execute_after_rotate");
        // the removed key no longer counts, even alongside a current one
        bytes memory withRemoved = _multisig("execute_after_rotate", _keys(2, 0));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, withRemoved);
        // the rotated-in key does
        _execute("execute_after_rotate", _keys(3, 0));
        assertTrue(treasury.executed(c.proposalId));
    }

    function test_ReconfigurationCannotBeReplayed() public {
        _reconfigure("reconfigure_rotate", _keys(0, 1));
        Change memory c = _change("reconfigure_rotate");
        bytes memory multisig = _multisig("reconfigure_rotate", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_ReconfigurationsApplyOnlyInOrder() public {
        // reconfigure_lower was signed for nonce 2. Keys 0 and 1 ARE signers at nonce 0, so this
        // reaches the signature check and fails there, on the nonce, not on membership.
        Change memory c = _change("reconfigure_lower");
        assertTrue(treasury.isSigner(_signer(0)) && treasury.isSigner(_signer(1)));
        bytes memory multisig = _multisig("reconfigure_lower", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_ExpiredReconfigurationIsRejected() public {
        Change memory c = _change("reconfigure_rotate");
        bytes memory multisig = _multisig("reconfigure_rotate", _keys(0, 1));
        vm.warp(uint256(c.validUntil) + 1);
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.Expired.selector, c.validUntil));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_RaiseThenLowerTheThreshold() public {
        _reconfigure("reconfigure_rotate", _keys(0, 1));
        _reconfigure("reconfigure_raise", _keys(0, 1, 3));
        assertEq(treasury.threshold(), 3);

        Call memory c = _call("execute_three");
        bytes memory two = _multisig("execute_three", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, two);

        // 3-of-3 {0, 1, 3} -> 2-of-2 {0, 1}: only valid if the threshold drops BEFORE the removal
        _reconfigure("reconfigure_lower", _keys(0, 1, 3));
        assertEq(treasury.threshold(), 2);
        assertEq(treasury.getSignerCount(), 2);
        assertFalse(treasury.isSigner(_signer(3)));

        _execute("execute_three", _keys(0, 1)); // now two suffice
        assertTrue(treasury.executed(c.proposalId));
    }

    /// One field changed per run (re-review finding 6). The nonce is covered separately, by
    /// test_ReconfigurationCannotBeReplayed and test_ReconfigurationsApplyOnlyInOrder.
    /// forge-config: default.fuzz.runs = 48
    function testFuzz_ChangingAnyOneReconfigureFieldIsRejected(uint8 field, uint64 random) public {
        Change memory c = _change("reconfigure_rotate");
        field = uint8(bound(field, 0, 3));
        if (field == 0) {
            vm.assume(random != c.threshold);
            c.threshold = random;
        } else if (field == 1) {
            uint64 later = uint64(bound(random, block.timestamp, type(uint64).max));
            vm.assume(later != c.validUntil);
            c.validUntil = later;
        } else if (field == 2) {
            c.add = new bytes[](0);
        } else {
            c.remove = new bytes[](0);
        }
        bytes memory multisig = _multisig("reconfigure_rotate", _keys(0, 1));
        vm.expectRevert(QVaultTreasury.InvalidMultisig.selector);
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_MoveAKeyToNewStorageInOneStep() public {
        // Remove key 0's identity and add the same key under fresh pointers, in one approval. The
        // key is released before the additions, so this is not mistaken for a duplicate.
        bytes memory moved = vm.parseJsonBytes(_json(), ".duplicate_of_key0.signer");
        _reconfigure("reconfigure_move_key", _keys(0, 1));
        assertTrue(treasury.isSigner(moved));
        assertFalse(treasury.isSigner(_signer(0)));
        assertTrue(treasury.keyInUse(_keyId(0)), "the moved key is still held");
        assertEq(treasury.getSignerCount(), 3);

        // Key 0's signature now counts through its new identity.
        Call memory c = _call("execute_eth");
        bytes[] memory signers = new bytes[](2);
        bytes[] memory sigs = new bytes[](2);
        (signers[0], signers[1]) = (moved, _signer(1));
        (sigs[0], sigs[1]) = (_sig("execute_eth", 0), _sig("execute_eth", 1));
        treasury.execute(c.proposalId, c.to, c.value, c.data, c.callGas, c.validUntil, abi.encode(signers, sigs));
        assertTrue(treasury.executed(c.proposalId));
    }

    function test_ThresholdCapFitsUnderTheTransactionGasCap() public {
        _reconfigure("reconfigure_max", _keys(0, 1));
        assertEq(treasury.threshold(), treasury.MAX_THRESHOLD());
        assertEq(treasury.getSignerCount(), 8);

        bytes memory payload = _executeCalldata("execute_max", _keysUpTo(8));
        (bool ok,) = address(treasury).call(payload);
        assertTrue(ok);
        uint256 executionGas = vm.lastCallGas().gasTotalUsed;
        uint256 txGas = _txGas(executionGas, payload);
        console.log("execute at the cap (8 signatures), gas:", executionGas);
        console.log("execute at the cap, tx gas incl. calldata:", txGas);
        console.log("headroom under EIP-7825 cap:", TX_GAS_CAP - txGas);
        assertLt(txGas, TX_GAS_CAP * 90 / 100, "the cap must leave at least 10% headroom");
    }

    function test_ThresholdAboveTheCapIsRefusedEvenWhenApproved() public {
        Change memory c = _change("reconfigure_too_high");
        bytes memory multisig = _multisig("reconfigure_too_high", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ThresholdTooHigh.selector, uint64(9), uint64(8)));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_ApprovedReconfigurationCannotAddAForeignSigner() public {
        Change memory c = _change("reconfigure_foreign");
        bytes memory multisig = _multisig("reconfigure_foreign", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ForeignSigner.selector, c.add[0]));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_ApprovedReconfigurationCannotAddTheSameKeyTwice() public {
        // Review finding 1: key 0's content under a second pair of pointers is a different 124-byte
        // identity. Without the content check, one approver would count as two.
        Change memory c = _change("reconfigure_duplicate");
        bytes memory multisig = _multisig("reconfigure_duplicate", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.DuplicateKey.selector, _keyId(0)));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_ApprovedReconfigurationCannotAddMismatchedContent() public {
        Change memory c = _change("reconfigure_mismatch");
        bytes memory multisig = _multisig("reconfigure_mismatch", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.KeyContentMismatch.selector, c.add[0]));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
    }

    function test_UnreachableThresholdIsRefusedAndSpendsNothing() public {
        Change memory c = _change("reconfigure_unreachable");
        bytes memory multisig = _multisig("reconfigure_unreachable", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(MultiSignerERC7913.MultiSignerERC7913UnreachableThreshold.selector, 1, 2));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
        assertEq(treasury.configNonce(), 0, "a refused reconfiguration must not use up the nonce");
        assertTrue(treasury.keyInUse(_keyId(0)), "nor release any key");
    }

    function test_RemovingANonMemberIsRefused() public {
        Change memory c = _change("reconfigure_remove_nonmember");
        bytes memory multisig = _multisig("reconfigure_remove_nonmember", _keys(0, 1));
        vm.expectRevert(abi.encodeWithSelector(MultiSignerERC7913.MultiSignerERC7913NonexistentSigner.selector, c.remove[0]));
        treasury.reconfigure(c.add, c.remove, c.threshold, c.validUntil, multisig);
        assertEq(treasury.configNonce(), 0);
    }

    // --- 4. construction --------------------------------------------------------------------------

    function test_ConstructorRejectsAnEcdsaAddressSigner() public {
        bytes[] memory signers = _initialSigners();
        signers[2] = abi.encodePacked(address(0xEC05A));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ForeignSigner.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_ConstructorRejectsAnotherVerifier() public {
        bytes[] memory signers = _initialSigners();
        signers[1] = vm.parseJsonBytes(_json(), ".foreign_signer"); // the identity precompile
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ForeignSigner.selector, signers[1]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_ConstructorRejectsAMalformedSigner() public {
        bytes[] memory signers = _initialSigners();
        signers[0] = abi.encodePacked(signers[0], hex"00"); // 125 bytes
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ForeignSigner.selector, signers[0]));
        new QVaultTreasury(address(verifier), signers, 2);
        // and the pre-D17 60-byte form
        signers[0] = abi.encodePacked(address(verifier), _pointers(0));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ForeignSigner.selector, signers[0]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_ConstructorRejectsMismatchedKeyContent() public {
        bytes[] memory signers = _initialSigners();
        signers[2] = vm.parseJsonBytes(_json(), ".mismatched_signer");
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.KeyContentMismatch.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_ConstructorRejectsKeyPointersWithNoCode() public {
        // Content hashes of a real key, pointing at addresses where nothing is stored (yet). This
        // is the front-running shape: an identity built from predicted, unconfirmed pointers.
        bytes[] memory signers = _initialSigners();
        bytes memory handle = _handle(2);
        for (uint256 i = 0; i < 40; i++) {
            handle[i] = bytes1(uint8(0x11));
        }
        signers[2] = abi.encodePacked(address(verifier), handle);
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.NonCanonicalKeyStorage.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_AnIdentityCannotBeAddedBeforeItsKeyIsStored() public {
        // Re-review finding 2: EXTCODEHASH of an address with nothing there is 0, and of a funded
        // address with no code is keccak(""). An identity claiming either used to pass, leaving the
        // key to be decided by whoever later deployed at those addresses.
        address a = address(0xE0E0);
        address b = address(0xE0E1);
        bytes[] memory signers = _initialSigners();

        signers[2] = abi.encodePacked(address(verifier), a, b, a.codehash, b.codehash);
        assertEq(a.codehash, bytes32(0));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.NonCanonicalKeyStorage.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);

        vm.deal(a, 1);
        vm.deal(b, 1);
        signers[2] = abi.encodePacked(address(verifier), a, b, a.codehash, b.codehash);
        assertEq(a.codehash, keccak256(""));
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.NonCanonicalKeyStorage.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_StorageThatCouldSelfDestructIsRefused() public {
        // Key 2's genuine halves, but behind a first byte that executes (0xff, SELFDESTRUCT)
        // instead of STOP: storage that could be destroyed and redeployed with other content.
        bytes memory blob = _blob(2);
        address a = address(0x5E1F0);
        address b = address(0x5E1F1);
        vm.etch(a, abi.encodePacked(hex"ff", _slice(blob, 0, 20_160)));
        vm.etch(b, abi.encodePacked(hex"ff", _slice(blob, 20_160, 20_160)));
        assertEq(a.code.length, 20_161, "right length, wrong first byte");

        bytes[] memory signers = _initialSigners();
        signers[2] = abi.encodePacked(address(verifier), a, b, a.codehash, b.codehash);
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.NonCanonicalKeyStorage.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_CanonicalLookingStorageWithoutAReadableKeyIsRefused() public {
        // STOP-prefixed, the right length, and matching hashes, but no tr where the verifier would
        // look for it.
        bytes memory junk = new bytes(20_160);
        for (uint256 i = 0; i < 64; i++) {
            junk[i] = 0xff; // head words: offsets far outside the half
        }
        address a = address(0x7A70);
        address b = address(0x7A71);
        vm.etch(a, abi.encodePacked(hex"00", junk));
        vm.etch(b, abi.encodePacked(hex"00", junk));

        bytes[] memory signers = _initialSigners();
        signers[2] = abi.encodePacked(address(verifier), a, b, a.codehash, b.codehash);
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.NonCanonicalKeyStorage.selector, signers[2]));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_AReencodedCopyOfAKeyCannotCountTwice() public {
        // Re-review finding 3. The verifier takes tr from half 0 only, so changing half 1's copy of
        // tr gives different storage, different code hashes and a different identity, under which
        // key 0's signatures still verify. Comparing whole-blob hashes counted it as a second key.
        bytes memory blob = _blob(0);
        uint256 trOffset = uint256(_word(blob, 20_160 + 32)); // half 1's second head word
        blob[20_160 + trOffset + 32] ^= 0x01;
        bytes memory pointers = verifier.setKey(blob);
        (address a, address b) = (_pointerAt(pointers, 0), _pointerAt(pointers, 1));
        bytes memory reencoded = abi.encodePacked(address(verifier), pointers, a.codehash, b.codehash);
        assertTrue(keccak256(reencoded) != keccak256(_signer(0)), "a genuinely different identity");

        // It really is a working encoding of key 0: the attack this closes is not hypothetical.
        Call memory c = _call("execute_eth");
        assertEq(verifier.verify(pointers, c.digest, _sig("execute_eth", 0)), ISigVerifier.verify.selector);

        bytes[] memory signers = _initialSigners();
        signers[2] = reencoded;
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.DuplicateKey.selector, _keyId(0)));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_ConstructorRejectsTheSameKeyTwice() public {
        bytes[] memory signers = _initialSigners();
        signers[2] = vm.parseJsonBytes(_json(), ".duplicate_of_key0.signer");
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.DuplicateKey.selector, _keyId(0)));
        new QVaultTreasury(address(verifier), signers, 2);
    }

    function test_ConstructorRejectsAVerifierWithNoCode() public {
        address nothing = address(0xDEAD);
        vm.expectRevert(abi.encodeWithSelector(VerifierBound.VerifierHasNoCode.selector, nothing));
        new QVaultTreasury(nothing, _initialSigners(), 2);
    }

    function test_ConstructorRejectsAnUnreachableThreshold() public {
        vm.expectRevert(abi.encodeWithSelector(MultiSignerERC7913.MultiSignerERC7913UnreachableThreshold.selector, 3, 4));
        new QVaultTreasury(address(verifier), _initialSigners(), 4);
    }

    function test_ConstructorRejectsZeroAndOverCapThresholds() public {
        vm.expectRevert(MultiSignerERC7913.MultiSignerERC7913ZeroThreshold.selector);
        new QVaultTreasury(address(verifier), _initialSigners(), 0);
        vm.expectRevert(abi.encodeWithSelector(QVaultTreasury.ThresholdTooHigh.selector, uint64(9), uint64(8)));
        new QVaultTreasury(address(verifier), _initialSigners(), 9);
    }

    function test_ExposesItsVerifier() public view {
        assertEq(treasury.verifier(), address(verifier));
    }
}
