"""The Recovery Kit's exact bytes and its code's typo check (plan R9, design §5.1 and §15).

The vectors in ``tests/vectors/recovery_kit.json`` were derived from the design's text with other
means (polynomial long division for the CRC, byte strings built by hand, the KDF libraries
directly), so these tests compare two derivations, not the code with itself. The browser's check
(``qvault/static/recover.js``) is run against the same vectors in Node.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from qvault.crypto import kit_code
from qvault.crypto.kdf import derive_kek, hkdf_sha256
from qvault.security import master_key
from qvault.services import recovery_kit

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((ROOT / "tests/vectors/recovery_kit.json").read_text(encoding="utf-8"))
B = VECTORS["bytes"]


def _long_division(value: int) -> int:
    generator = (1 << 10) | 0x233
    remainder = value << 10
    for bit in range(159, 9, -1):
        if remainder >> bit & 1:
            remainder ^= generator << (bit - 10)
    return remainder


# --------------------------------------------------------------------------------------------
# The code


@pytest.mark.parametrize("vector", VECTORS["codes"], ids=lambda v: v["grouped"])
def test_a_fixed_k_encodes_to_its_vector_code_and_check(vector):
    k = int(vector["k_hex"], 16)
    code = kit_code.encode(k)
    assert code == vector["code"]
    assert kit_code.grouped(code) == vector["grouped"]
    assert kit_code.crc10(k) == vector["crc"] == _long_division(k)
    assert kit_code.decode(vector["grouped"]) == k
    assert kit_code.argon2_input(code) == vector["argon2_input"]


@pytest.mark.parametrize("vector", VECTORS["typed"], ids=lambda v: repr(v["typed"])[:40])
def test_typed_codes_normalise_or_are_refused_as_the_vectors_say(vector):
    if vector["normalised"] is None:
        with pytest.raises(kit_code.KitCodeError):
            kit_code.normalise(vector["typed"])
    else:
        assert kit_code.normalise(vector["typed"]) == vector["normalised"]


def test_the_symbol_at_a_time_crc_equals_the_bit_at_a_time_definition():
    rng = random.Random(150)
    for bits in (5, 10, 150, 160):
        for _ in range(2000):
            value = rng.getrandbits(bits)
            assert kit_code.crc10(value, bits) == kit_code._crc_bits(value, bits)


def test_every_codeword_is_a_multiple_of_the_generator():
    rng = random.Random(7)
    for _ in range(2000):
        k = rng.getrandbits(150)
        assert kit_code.crc10((k << 10) | kit_code.crc10(k), 160) == 0


def test_encoding_and_decoding_are_inverse_over_ten_thousand_codes():
    rng = random.Random(10_000)
    for _ in range(10_000):
        k = rng.getrandbits(150)
        code = kit_code.encode(k)
        assert len(code) == 32 and kit_code.decode(code) == k
        assert kit_code.decode(kit_code.grouped(code).lower()) == k


def test_every_single_character_substitution_of_a_thousand_codes_is_caught():
    rng = random.Random(1000)
    missed = []
    for _ in range(1000):
        code = kit_code.encode(rng.getrandbits(150))
        for i in range(32):
            for symbol in kit_code.ALPHABET:
                if symbol == code[i]:
                    continue
                try:
                    kit_code.normalise(code[:i] + symbol + code[i + 1 :])
                except kit_code.KitCodeError:
                    continue
                missed.append((code, i, symbol))
    assert missed == []


def test_every_swap_of_two_neighbouring_characters_of_a_thousand_codes_is_caught():
    rng = random.Random(1001)
    missed = []
    swaps = 0
    for _ in range(1000):
        code = kit_code.encode(rng.getrandbits(150))
        for i in range(31):
            if code[i] == code[i + 1]:
                continue  # swapping equal characters changes nothing
            swaps += 1
            swapped = code[:i] + code[i + 1] + code[i] + code[i + 2 :]
            try:
                kit_code.normalise(swapped)
            except kit_code.KitCodeError:
                continue
            missed.append((code, i))
    assert missed == [] and swaps > 29_000


def test_case_spaces_hyphens_and_the_letters_i_l_and_o_are_read_as_people_mean_them():
    code = VECTORS["codes"][6]["code"]
    messy = "  " + "-".join(code[i : i + 4] for i in range(0, 32, 4)).lower() + " "
    assert kit_code.normalise(messy) == code
    assert kit_code.normalise(code.replace("1", "i").replace("0", "o")) == code
    assert kit_code.normalise(code.replace("1", "L")) == code


def test_a_u_or_a_wrong_length_is_refused_with_a_sentence_saying_which():
    code = VECTORS["codes"][7]["code"]
    with pytest.raises(kit_code.KitCodeError, match="never uses"):
        kit_code.normalise(code[:5] + "U" + code[6:])
    with pytest.raises(kit_code.KitCodeError, match="That one has 31"):
        kit_code.normalise(code[:31])


def test_a_fresh_code_is_150_random_bits_from_the_system_generator():
    seen = {kit_code.new_code()[1] for _ in range(200)}
    assert len(seen) == 200
    for k, code in (kit_code.new_code() for _ in range(50)):
        assert 0 <= k < 2**150 and kit_code.decode(code) == k


# --------------------------------------------------------------------------------------------
# The bytes around it


def test_the_argon2id_input_is_the_thirty_data_symbols_as_ascii():
    argon = B["argon2"]
    output = derive_kek(
        argon["input"], bytes.fromhex(argon["salt_hex"]), length=32, **argon["params"]
    )
    assert output.hex() == argon["output_hex"]
    assert len(argon["input"]) == 30 and argon["input"].isascii()


def test_the_pepper_hkdf_aad_and_mac_bytes_are_the_designs(app):
    app.config["SERVER_MASTER_KEY"] = B["master_key_hex"]
    uuid, user_id, key_id = B["kit_uuid"], B["user_id"], B["key_id"]
    public_key = bytes.fromhex(B["public_key_hex"])

    assert master_key.kit_pepper(uuid).hex() == B["pepper_hex"]
    assert recovery_kit.kek_info(uuid, user_id).decode() == B["kek_info"]
    assert recovery_kit.kem_sk_aad(uuid, user_id).decode() == B["kem_sk_aad"]
    assert recovery_kit.wrap_info(uuid, key_id).decode() == B["wrap_info"]
    assert recovery_kit.wrap_aad(uuid, key_id, public_key).decode() == B["wrap_aad"]
    assert recovery_kit.selftest_message(uuid, key_id).decode() == B["selftest_message"]

    mac_input = recovery_kit.pk_mac_input(user_id, uuid, B["kem_alg"], B["created_at"], public_key)
    assert mac_input.hex() == B["pk_mac_input_hex"]
    assert master_key.kit_pk_mac(mac_input).hex() == B["pk_mac_hex"]

    argon = B["argon2"]
    code = kit_code.normalise(VECTORS["codes"][5]["code"])
    kek = recovery_kit.derive_kit_kek(
        code, bytes.fromhex(argon["salt_hex"]), argon["params"], uuid, user_id
    )
    assert kek.hex() == B["kit_kek_hex"]
    dek = hkdf_sha256(bytes.fromhex(B["kem_shared_secret_hex"]), info=B["wrap_info"].encode())
    assert dek.hex() == B["dek_hex"]


def test_the_kit_tags_are_their_own_and_never_the_system_keys(app):
    data = b"the same bytes"
    assert master_key.kit_pk_mac(data) != master_key.mac(data)
    assert master_key.kit_pk_mac(data) != master_key.challenge_mac(data)
    assert master_key.kit_pepper("x") != master_key.kit_pk_mac(b"x")
    assert not master_key.verify_mac(data, master_key.kit_pk_mac(data))
    assert master_key.kit_confirm_tag("x", "ABCD") != master_key.kit_pk_mac(b"x|ABCD")
    assert master_key.kit_confirm_tag("x", "ABCD") != master_key.kit_pepper("x|ABCD")


# --------------------------------------------------------------------------------------------
# The browser's check, from the same vectors

_NODE_CHECK = r"""
const kit = require(process.argv[2]);
const vectors = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const out = { codes: [], typed: [] };
for (const v of vectors.codes) {
  const r = kit.normalise(v.grouped.toLowerCase());
  const values = [];
  for (let i = 0; i < 30; i++) values.push(kit.ALPHABET.indexOf(v.code[i]));
  out.codes.push({ code: r.ok ? r.code : null, crc: kit.crc10(values) });
}
for (const v of vectors.typed) {
  const r = kit.normalise(v.typed);
  out.typed.push(r.ok ? { normalised: r.code } : { normalised: null, reason: r.reason });
}
process.stdout.write(JSON.stringify(out));
"""


def test_the_browsers_check_agrees_with_every_vector(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    script = tmp_path / "check.js"
    script.write_text(_NODE_CHECK, encoding="utf-8")
    result = subprocess.run(
        [
            node,
            str(script),
            str(ROOT / "qvault/static/recover.js"),
            str(ROOT / "tests/vectors/recovery_kit.json"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    seen = json.loads(result.stdout)
    for vector, got in zip(VECTORS["codes"], seen["codes"], strict=True):
        assert got == {"code": vector["code"], "crc": vector["crc"]}
    for vector, got in zip(VECTORS["typed"], seen["typed"], strict=True):
        assert got["normalised"] == vector["normalised"]
        if vector["normalised"] is None:
            assert got["reason"] == vector["reason"]


def test_the_browsers_typo_messages_are_the_servers():
    source = (ROOT / "qvault/static/recover.js").read_text(encoding="utf-8")
    for typed in ("U" * 32, "0" * 31):
        with pytest.raises(kit_code.KitCodeError) as caught:
            kit_code.normalise(typed)
        sentence = str(caught.value)
        assert sentence.split(" That one has")[0] in source
