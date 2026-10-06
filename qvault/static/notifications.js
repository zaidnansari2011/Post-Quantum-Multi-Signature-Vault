// The bell's popover (plan R4). Without this script the bell is a plain link to the inbox, and
// that link is also where it falls back if the popover cannot be fetched.
(function () {
  var bell = document.querySelector('[data-nbell]');
  if (!bell) return;
  var button = bell.querySelector('.nbell__button');
  var pop = bell.querySelector('.nbell__pop');
  var GAP = 8;

  // Beside the bell when there is room to its right (the rail), otherwise below it, right-aligned
  // (a top bar). Kept inside the viewport either way.
  function place() {
    var r = button.getBoundingClientRect();
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left, top;
    if (r.right + GAP + w <= window.innerWidth - GAP && r.left < window.innerWidth / 2) {
      left = r.right + GAP;
      top = r.top;
    } else {
      left = r.right - w;
      top = r.bottom + 6;
    }
    left = Math.max(GAP, Math.min(left, window.innerWidth - w - GAP));
    top = Math.max(GAP, Math.min(top, window.innerHeight - h - GAP));
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
  }

  function close(focusBell) {
    if (pop.hidden) return;
    pop.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    if (focusBell) button.focus();
  }

  function open() {
    fetch(bell.getAttribute('data-popover'), { credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        pop.innerHTML = html;
        pop.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        place();
        var first = pop.querySelector('a, button');
        if (first) first.focus();
      })
      .catch(function () { window.location.href = button.href; });
  }

  button.addEventListener('click', function (e) {
    // A modified click still opens the inbox in a new tab, as any link would.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    if (pop.hidden) open(); else close(false);
  });
  document.addEventListener('click', function (e) {
    if (!bell.contains(e.target)) close(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close(true);
  });
  window.addEventListener('resize', function () { if (!pop.hidden) place(); });
})();
