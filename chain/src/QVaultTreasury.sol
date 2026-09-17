// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MultiSignerERC7913} from "@openzeppelin/contracts/utils/cryptography/signers/MultiSignerERC7913.sol";
import {ReentrancyGuardTransient} from "@openzeppelin/contracts/utils/ReentrancyGuardTransient.sol";

/// @title VerifierBound
/// @notice Fixes the one ERC-7913 verifier every signer of a treasury must use.
/// @dev A separate base so that it is initialised *before* MultiSignerERC7913's constructor adds
///      the first signers. Base constructors run in inheritance order; had the verifier been set
///      in QVaultTreasury's own constructor body, the signer check in `_addSigners` would read an
///      unset immutable while the initial signers were being registered and reject all of them.
abstract contract VerifierBound {
    address internal immutable _VERIFIER;

    error VerifierHasNoCode(address verifier);

    constructor(address verifier_) {
        if (verifier_.code.length == 0) revert VerifierHasNoCode(verifier_);
        _VERIFIER = verifier_;
    }
}

/// @title QVaultTreasury
/// @notice Holds funds for one Q-Vault vault and moves them only on M-of-N ML-DSA-65 approvals,
///         checked here, on-chain. There is no owner, no admin and no upgrade path: the signer
///         set, and nothing else, controls this contract, including changes to the signer set.
/// @dev Anyone may submit an approved transaction, and whoever does gains no authority by it.
///      Everything that decides what happens (chain, contract, decision, recipient, amount,
///      calldata, the gas the call receives, and a deadline) is inside the digest the approvers
///      signed. See docs/plans/onchain-execution.md, decisions D3, D8 and D17-D20.
///
///      The digest functions have Python twins in qvault/chain/digest.py. They are held together
///      by chain/test/fixtures/treasury.json, which both test suites check.
contract QVaultTreasury is VerifierBound, MultiSignerERC7913, ReentrancyGuardTransient {
    bytes32 public constant EXECUTE_TAG = keccak256("QVAULT-TREASURY-v1:EXECUTE");
    bytes32 public constant RECONFIGURE_TAG = keccak256("QVAULT-TREASURY-v1:RECONFIGURE");

    /// @notice A signer is `verifier (20) || pointer0 (20) || pointer1 (20) || codehash0 (32) || codehash1 (32)`.
    /// @dev The verifier is given `pointer0 || pointer1 || codehash0 || codehash1` as its key and reads
    ///      only the first 40 bytes. The code hashes are for this contract: they make a signer's
    ///      identity commit to the key *content*, not merely to where it is stored (D17).
    uint256 public constant SIGNER_BYTES = 124;

    /// @notice Every signature costs ~1.55M gas to verify, and a transaction may use at most
    ///         16,777,216 (EIP-7825). 10 signatures measured ~16.04M including calldata; 11 cannot
    ///         execute at all, which would lock the treasury forever. 8 keeps real headroom (D19).
    uint64 public constant MAX_THRESHOLD = 8;

    /// @notice Calldata copied to memory is paid for after the gas check, so it must stay small
    ///         enough never to eat into CALL_RESERVE. Q-Vault's own calls are 0-68 bytes (D18).
    uint256 public constant MAX_CALL_DATA_BYTES = 4096;

    /// @dev Gas held back beyond what the call itself receives: the cold-account, value-transfer
    ///      and new-account surcharges charged to the caller (worst case ~39k), and the bookkeeping
    ///      after the call returns.
    uint256 internal constant CALL_RESERVE = 50_000;

    /// @dev ZKNOX_dilithium65 stores each half of an expanded key as SSTORE2 code: a STOP byte,
    ///      then exactly 20,160 bytes of `abi.encode(bytes aHat, bytes tr, bytes t1)`.
    uint256 internal constant KEY_HALF_BYTES = 20_160;
    uint256 internal constant POINTER_CODE_BYTES = KEY_HALF_BYTES + 1;

    /// @notice Decisions already carried out, by the decision's Q-Vault payload_hash.
    mapping(bytes32 proposalId => bool) public executed;

    /// @notice Bound into every reconfiguration digest, so each one applies exactly once.
    uint256 public configNonce;

    /// @notice Keys currently held by some signer, by keccak256(tr) (see _keyIdOf).
    mapping(bytes32 keyId => bool) public keyInUse;

    event Executed(bytes32 indexed proposalId, address indexed to, uint256 value, bytes32 dataHash);
    event Reconfigured(uint256 indexed configNonce, uint256 added, uint256 removed, uint64 threshold);
    event Deposited(address indexed from, uint256 value);

    error AlreadyExecuted(bytes32 proposalId);
    error InvalidMultisig();
    error Expired(uint64 validUntil);
    error CallDataTooLarge(uint256 length, uint256 max);
    error InsufficientGas(uint256 available, uint256 required);
    error CallFailed(bytes returndata);
    error ForeignSigner(bytes signer);
    error NonCanonicalKeyStorage(bytes signer);
    error KeyContentMismatch(bytes signer);
    error DuplicateKey(bytes32 keyId);
    error ThresholdTooHigh(uint64 threshold, uint64 max);

    constructor(address verifier_, bytes[] memory signers_, uint64 threshold_)
        VerifierBound(verifier_)
        MultiSignerERC7913(signers_, threshold_)
    {}

    receive() external payable {
        emit Deposited(msg.sender, msg.value);
    }

    /// @notice The ERC-7913 verifier every signer of this treasury is checked by.
    function verifier() external view returns (address) {
        return _VERIFIER;
    }

    /// @notice What M approvers sign to allow one call.
    function executionDigest(
        bytes32 proposalId,
        address to,
        uint256 value,
        bytes calldata data,
        uint64 callGas,
        uint64 validUntil
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                EXECUTE_TAG,
                block.chainid,
                address(this),
                proposalId,
                to,
                value,
                keccak256(data),
                callGas,
                validUntil
            )
        );
    }

    /// @notice What M approvers sign to change the signer set or the threshold.
    function reconfigureDigest(
        uint256 nonce,
        bytes[] calldata add,
        bytes[] calldata remove,
        uint64 newThreshold,
        uint64 validUntil
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                RECONFIGURE_TAG,
                block.chainid,
                address(this),
                nonce,
                keccak256(abi.encode(add)),
                keccak256(abi.encode(remove)),
                newThreshold,
                validUntil
            )
        );
    }

    /// @notice Carry out an approved decision.
    /// @param callGas exactly the gas the call receives; the transaction must carry enough for it.
    /// @param validUntil the last block timestamp at which this approval can be used.
    /// @param multisig abi.encode(bytes[] signers, bytes[] signatures), see MultiSignerERC7913.
    /// @dev The decision is marked executed before the external call, and the whole transaction
    ///      reverts if that call fails. So a decision is never recorded as done without its effect,
    ///      and a failed one (say, an unfunded treasury) can be submitted again until it expires.
    ///      Forwarding exactly `callGas`, and refusing to start unless it can be forwarded, stops a
    ///      submitter from choosing a gas limit that starves a target which swallows its own errors.
    function execute(
        bytes32 proposalId,
        address to,
        uint256 value,
        bytes calldata data,
        uint64 callGas,
        uint64 validUntil,
        bytes calldata multisig
    ) external nonReentrant returns (bytes memory result) {
        if (executed[proposalId]) revert AlreadyExecuted(proposalId);
        // A validator can shift block.timestamp by seconds; deadlines here are hours to days.
        // forge-lint: disable-next-line(block-timestamp)
        if (block.timestamp > validUntil) revert Expired(validUntil);
        if (data.length > MAX_CALL_DATA_BYTES) revert CallDataTooLarge(data.length, MAX_CALL_DATA_BYTES);
        if (!_rawSignatureValidation(executionDigest(proposalId, to, value, data, callGas, validUntil), multisig)) {
            revert InvalidMultisig();
        }
        executed[proposalId] = true;

        // EIP-150: a call can forward at most 63/64 of the gas remaining.
        uint256 required = (uint256(callGas) * 64) / 63 + CALL_RESERVE;
        if (gasleft() < required) revert InsufficientGas(gasleft(), required);

        bool ok;
        (ok, result) = to.call{gas: callGas, value: value}(data);
        if (!ok) revert CallFailed(result);

        emit Executed(proposalId, to, value, keccak256(data));
    }

    /// @notice Add and remove signers and set the threshold, approved by the current signers.
    /// @dev Removed keys are released first, so one reconfiguration can move a key to new storage
    ///      (remove its old identity, add the new one) without tripping the duplicate check. The
    ///      set itself is still changed add-first, and the threshold moves whichever way keeps it
    ///      reachable at every intermediate step: lowered before removals, raised after. Any
    ///      invalid step reverts the whole transaction, releases included.
    function reconfigure(
        bytes[] calldata add,
        bytes[] calldata remove,
        uint64 newThreshold,
        uint64 validUntil,
        bytes calldata multisig
    ) external nonReentrant {
        // forge-lint: disable-next-line(block-timestamp)
        if (block.timestamp > validUntil) revert Expired(validUntil);
        uint256 nonce = configNonce;
        if (!_rawSignatureValidation(reconfigureDigest(nonce, add, remove, newThreshold, validUntil), multisig)) {
            revert InvalidMultisig();
        }
        configNonce = nonce + 1;

        _releaseKeys(remove);
        _addSigners(add);
        if (newThreshold < threshold()) {
            _setThreshold(newThreshold);
            _removeSigners(remove);
        } else {
            _removeSigners(remove);
            _setThreshold(newThreshold);
        }

        emit Reconfigured(nonce, add.length, remove.length, newThreshold);
    }

    /// @dev Every signer must be an ML-DSA-65 key checked by this treasury's verifier, held in
    ///      canonical storage whose code hashes match its identity, and not already held by
    ///      another signer (D17).
    ///
    ///      OpenZeppelin accepts any `verifier || key` blob, including a bare 20-byte address that
    ///      would be checked with ECDSA, or a "verifier" such as the identity precompile that
    ///      approves everything; the length and verifier checks refuse both.
    ///
    ///      Canonical storage means exactly the code SSTORE2 writes: 20,161 bytes, starting with a
    ///      STOP byte. An address holding nothing (code hash 0, or keccak("") once funded) can't
    ///      pass, so no identity can be added ahead of its key and filled in later by whoever
    ///      deploys there. Storage that begins with STOP can never run, so it can never
    ///      self-destruct and be replaced. The code-hash check then means approving an identity
    ///      approves specific key content, which anyone can recompute from a public key.
    ///
    ///      Keys are compared by `tr`, not by whole-blob hash. `tr = SHAKE256(pk, 64)` is what the
    ///      verifier feeds into every signature check, read from half 0, so any encoding under
    ///      which an honest holder's signatures verify carries the same `tr`. A re-encoding that
    ///      differs only in bytes the verifier ignores therefore can't make one approver count
    ///      as two.
    ///
    ///      What cannot be checked here is whether the content is a *genuine* ML-DSA-65 key,
    ///      because expanding a key on-chain costs more than verifying with it. An all-zero key
    ///      would be forgeable by anyone. So whoever links the treasury, and every approver of a
    ///      reconfiguration, must compute the identity from the real public key
    ///      (qvault/chain/digest.py: signer_blob).
    function _addSigners(bytes[] memory newSigners) internal virtual override {
        for (uint256 i = 0; i < newSigners.length; ++i) {
            bytes memory signer = newSigners[i];
            if (signer.length != SIGNER_BYTES) revert ForeignSigner(signer);
            (address verifier_, address pointer0, address pointer1, bytes32 codehash0, bytes32 codehash1) =
                _parseSigner(signer);
            if (verifier_ != _VERIFIER) revert ForeignSigner(signer);
            if (!_isCanonicalStorage(pointer0) || !_isCanonicalStorage(pointer1)) revert NonCanonicalKeyStorage(signer);
            if (pointer0.codehash != codehash0 || pointer1.codehash != codehash1) revert KeyContentMismatch(signer);

            (bytes32 keyId, bool readable) = _keyIdOf(pointer0);
            if (!readable) revert NonCanonicalKeyStorage(signer);
            if (keyInUse[keyId]) revert DuplicateKey(keyId);
            keyInUse[keyId] = true;
        }
        super._addSigners(newSigners);
    }

    function _setThreshold(uint64 newThreshold) internal virtual override {
        if (newThreshold > MAX_THRESHOLD) revert ThresholdTooHigh(newThreshold, MAX_THRESHOLD);
        super._setThreshold(newThreshold);
    }

    /// @dev Mark the keys of signers about to be removed as free. Only a current signer can be
    ///      removed, and current signers passed _addSigners, so their storage is canonical and
    ///      readable; anything else makes the later removal revert, undoing this with it.
    function _releaseKeys(bytes[] calldata oldSigners) private {
        for (uint256 i = 0; i < oldSigners.length; ++i) {
            if (oldSigners[i].length != SIGNER_BYTES) continue;
            (, address pointer0,,,) = _parseSigner(oldSigners[i]);
            (bytes32 keyId, bool readable) = _keyIdOf(pointer0);
            if (readable) delete keyInUse[keyId];
        }
    }

    function _isCanonicalStorage(address pointer) private view returns (bool canonical) {
        if (pointer.code.length != POINTER_CODE_BYTES) return false;
        assembly ("memory-safe") {
            let m := mload(0x40)
            extcodecopy(pointer, m, 0, 1)
            canonical := iszero(byte(0, mload(m)))
        }
    }

    /// @dev keccak256 of the 64-byte `tr` in half 0, located exactly as ZKNOX_dilithium65 locates
    ///      it (readPubKeyPacked65): the second head word of the half gives the offset of a
    ///      `bytes` whose length must be 64. `readable` is false if the layout isn't that.
    function _keyIdOf(address pointer0) private view returns (bytes32 keyId, bool readable) {
        assembly ("memory-safe") {
            let m := mload(0x40)
            // code = STOP || half; head words of the half start one byte in
            extcodecopy(pointer0, m, 1, 64)
            let trOffset := mload(add(m, 32))
            if lt(trOffset, sub(KEY_HALF_BYTES, 95)) {
                extcodecopy(pointer0, m, add(1, trOffset), 96)
                if eq(mload(m), 64) {
                    keyId := keccak256(add(m, 32), 64)
                    readable := 1
                }
            }
        }
    }

    /// @dev Caller guarantees `signer.length == SIGNER_BYTES`.
    function _parseSigner(bytes memory signer)
        private
        pure
        returns (address verifier_, address pointer0, address pointer1, bytes32 codehash0, bytes32 codehash1)
    {
        assembly ("memory-safe") {
            let base := add(signer, 32)
            verifier_ := shr(96, mload(base))
            pointer0 := shr(96, mload(add(base, 20)))
            pointer1 := shr(96, mload(add(base, 40)))
            codehash0 := mload(add(base, 60))
            codehash1 := mload(add(base, 92))
        }
    }
}
