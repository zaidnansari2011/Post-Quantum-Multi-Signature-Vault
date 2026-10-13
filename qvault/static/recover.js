/* The Recovery Kit in the browser (plan R9, design §5.1 and §5.4).

   - The code's typo check, the same as the server's (qvault/crypto/kit_code.py) and run against
     the same vectors (tests/vectors/recovery_kit.json, tests/test_recovery_vectors.py). It only
     saves a round trip: the server checks again, and nothing here decides anything.
   - The kit page's download: a text file made here, from the page, never fetched.
   - The last group typed back, compared with the page before the form is sent.

   Loaded as a plain script in the page, and by Node in the vector test (module.exports). */
(function (root) {
  'use strict';

  var ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  var ALIASES = { I: '1', L: '1', O: '0' };
  var POLY = 0x233; // x^10 + x^9 + x^5 + x^4 + x + 1, without its x^10 term
  var DATA_SYMBOLS = 30;
  var SYMBOLS = 32;

  /* CRC-10 over a list of 5-bit values, most significant bit first, initial 0, no reflection. */
  function crc10(values) {
    var crc = 0;
    for (var i = 0; i < values.length; i++) {
      for (var b = 4; b >= 0; b--) {
        var top = ((crc >> 9) & 1) ^ ((values[i] >> b) & 1);
        crc = (crc << 1) & 0x3ff;
        if (top) crc ^= POLY;
      }
    }
    return crc;
  }

  /* {ok: true, code} with the 32 symbols meant, or {ok: false, reason, message}. */
  function normalise(typed) {
    var out = '';
    var text = String(typed == null ? '' : typed).toUpperCase();
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (ch === ' ' || ch === '-' || ch === '\t' || ch === '\r' || ch === '\n') continue;
      if (Object.prototype.hasOwnProperty.call(ALIASES, ch)) ch = ALIASES[ch];
      if (ALPHABET.indexOf(ch) < 0) {
        return {
          ok: false,
          reason: 'character',
          message: 'That code has a character a Recovery Kit never uses. Check it against your kit.',
        };
      }
      out += ch;
    }
    if (out.length !== SYMBOLS) {
      return {
        ok: false,
        reason: 'length',
        message:
          'A Recovery Kit code is 32 characters, in 8 groups of 4. That one has ' + out.length + '.',
      };
    }
    var values = [];
    for (var j = 0; j < DATA_SYMBOLS; j++) values.push(ALPHABET.indexOf(out.charAt(j)));
    var check = ALPHABET.indexOf(out.charAt(30)) * 32 + ALPHABET.indexOf(out.charAt(31));
    if (crc10(values) !== check) {
      return {
        ok: false,
        reason: 'check',
        message:
          'That code has a typo: one of its characters is wrong, or two are swapped. Check it against your kit.',
      };
    }
    return { ok: true, code: out };
  }

  function group(typed) {
    var out = '';
    var text = String(typed == null ? '' : typed).toUpperCase();
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (ch === ' ' || ch === '-') continue;
      out += Object.prototype.hasOwnProperty.call(ALIASES, ch) ? ALIASES[ch] : ch;
    }
    return out;
  }

  var api = { ALPHABET: ALPHABET, crc10: crc10, normalise: normalise, group: group };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
    return;
  }
  root.QVaultKit = api;
  if (typeof document === 'undefined') return;

  function showError(input, message) {
    var field = input.closest('.q-field');
    var box = field && field.querySelector('[data-kit-err]');
    if (!box && field) {
      box = document.createElement('p');
      box.className = 'q-field__err';
      box.setAttribute('data-kit-err', '');
      box.setAttribute('role', 'alert');
      box.id = input.id + '-kiterr';
      field.appendChild(box);
    }
    if (box) box.textContent = message;
    input.setAttribute('aria-invalid', 'true');
    var described = (input.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
    if (box && described.indexOf(box.id) < 0) described.push(box.id);
    input.setAttribute('aria-describedby', described.join(' '));
    input.focus();
  }

  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (form.hasAttribute('data-kit-entry')) {
      var input = form.querySelector('[data-kit-code]');
      var result = input ? normalise(input.value) : { ok: true };
      if (!result.ok) {
        event.preventDefault();
        showError(input, result.message);
      }
    }
    if (form.hasAttribute('data-kit-confirm')) {
      var last = document.querySelector('[data-kit-last]');
      var typed = form.querySelector('input[name="last_group"]');
      var mismatch = form.querySelector('[data-kit-mismatch]');
      if (last && typed && group(typed.value) !== last.textContent.trim()) {
        event.preventDefault();
        if (mismatch) mismatch.hidden = false;
        typed.setAttribute('aria-invalid', 'true');
        typed.focus();
      }
    }
  });

  var download = document.querySelector('[data-kit-download]');
  var file = document.querySelector('[data-kit-file]');
  if (download && file && window.Blob && window.URL) {
    download.hidden = false;
    download.removeAttribute('hidden');
    download.addEventListener('click', function () {
      var blob = new Blob([file.textContent], { type: 'text/plain;charset=utf-8' });
      var link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = file.getAttribute('data-kit-filename') || 'qvault-recovery-kit.txt';
      document.body.appendChild(link);
      link.click();
      setTimeout(function () {
        URL.revokeObjectURL(link.href);
        link.remove();
      }, 0);
    });
  }
})(this);
