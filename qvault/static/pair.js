/* Pair a phone by a code (A10, pairing-design §3.9): poll the pairing's state every 2 seconds while
   the page is visible, and reload when it changes, so the server draws the next step (the confirm
   card, or what happened). Nothing here computes anything: the check code is never known to the
   page, and the QR is drawn by the server. Stops at a state that cannot change. */
(function () {
  'use strict';
  var root = document.querySelector('[data-pair-poll]');
  if (!root) return;
  var url = root.getAttribute('data-pair-poll');
  var shown = root.getAttribute('data-pair-state');
  var live = { open: true, claimed: true };
  var confirm = document.getElementById('pair-confirm');
  if (confirm) confirm.focus();
  if (!live[shown]) return;

  var timer = null;
  function poll() {
    if (document.hidden) return;
    fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (view) {
        if (!view) return;
        if (view.state !== shown) {
          window.clearInterval(timer);
          window.location.reload();
          return;
        }
        if (shown === 'open' && view.scanned) {
          var line = document.getElementById('pair-state');
          if (line && line.textContent.indexOf('Scanned') !== 0) line.textContent = 'Scanned. Finish on the phone.';
        }
      })
      .catch(function () {});
  }
  timer = window.setInterval(poll, 2000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) poll(); });
})();
