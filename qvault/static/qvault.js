/* Q-Vault behaviours (rework S7): one small file, no framework, no build step, no network.
 *
 * Everything here is an enhancement. Each control already works as plain HTML: menus are <details>,
 * the theme choice and Sign out are forms, flashed messages are in the page, times are written out
 * in full. This file adds keyboard and pointer behaviour on top. Nothing here signs, decides or
 * hides anything: the server is the trusted renderer.
 *
 * Wiring is by delegated listeners on data-* attributes, never inline handlers, so the pages stay
 * compatible with a Content-Security-Policy that forbids inline script.
 */
(function () {
  'use strict';

  var doc = document;
  var root = doc.documentElement;

  /* ------------------------------------------------------------------ menus
   * <details data-menu>: native open and close; here Escape, outside click, one open at a time,
   * arrow keys between items, and focus back on the button. */

  function menuItems(menu) {
    return Array.prototype.slice.call(
      menu.querySelectorAll('.q-menu__panel a, .q-menu__panel button:not([disabled])')
    );
  }

  function closeMenu(menu, refocus) {
    if (!menu || !menu.open) return;
    menu.open = false;
    if (refocus) menu.querySelector('summary').focus();
  }

  function closeMenusExcept(keep) {
    doc.querySelectorAll('details[data-menu][open]').forEach(function (menu) {
      if (menu !== keep) closeMenu(menu, false);
    });
  }

  doc.addEventListener('toggle', function (e) {
    var menu = e.target;
    if (!menu.matches || !menu.matches('details[data-menu]') || !menu.open) return;
    closeMenusExcept(menu);
  }, true);

  doc.addEventListener('keydown', function (e) {
    var menu = e.target.closest && e.target.closest('details[data-menu]');
    if (!menu || !menu.open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      closeMenu(menu, true);
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
      var items = menuItems(menu);
      if (!items.length) return;
      e.preventDefault();
      var at = items.indexOf(doc.activeElement);
      var next;
      if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = items.length - 1;
      else if (e.key === 'ArrowDown') next = at < 0 ? 0 : (at + 1) % items.length;
      else next = at <= 0 ? items.length - 1 : at - 1;
      items[next].focus();
    }
  });

  /* ------------------------------------------------------------------ dialogs
   * <dialog> opened by [data-dialog-open="id"]; closed by [data-dialog-close], Escape (native) or
   * a click on the backdrop. Focus goes back to the opener. */

  var opener = null;

  function openDialog(dialog, from) {
    if (!dialog || typeof dialog.showModal !== 'function') return false;
    opener = from || doc.activeElement;
    dialog.showModal();
    return true;
  }

  doc.addEventListener('close', function (e) {
    if (e.target.tagName === 'DIALOG' && opener && doc.contains(opener)) {
      opener.focus();
      opener = null;
    }
  }, true);

  /* ------------------------------------------------------------------ copy
   * The Clipboard API needs a secure context; over plain HTTP (a LAN demo) it is missing, so fall
   * back to a hidden textarea and execCommand. */

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var area = doc.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      doc.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = doc.execCommand('copy'); } catch (err) { ok = false; }
      area.remove();
      if (ok) resolve(); else reject(new Error('copy failed'));
    });
  }

  function announce(message) {
    var live = doc.getElementById('q-live');
    if (!live) return;
    live.textContent = '';
    window.setTimeout(function () { live.textContent = message; }, 30);
  }

  /* ------------------------------------------------------------------ the shell: drawer and rail */

  function shell() { return doc.querySelector('[data-shell]'); }

  function setDrawer(open) {
    var s = shell();
    if (!s) return;
    s.classList.toggle('is-drawer', open);
    var button = doc.querySelector('[data-drawer-open]');
    if (button) button.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      var first = s.querySelector('.q-side a, .q-side button');
      if (first) first.focus();
    } else if (button) {
      button.focus();
    }
  }

  function setRail(on) {
    var s = shell();
    if (!s) return;
    s.classList.toggle('is-rail', on);
    var button = doc.querySelector('[data-rail-toggle]');
    if (button) {
      var label = on ? 'Expand sidebar' : 'Collapse sidebar';
      button.setAttribute('aria-label', label);
      button.setAttribute('title', label);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
    // Read by the server on the next page, so the rail is drawn collapsed from the first paint.
    doc.cookie = 'qv_rail=' + (on ? '1' : '0') + '; path=/; max-age=31536000; samesite=lax';
  }

  doc.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var s = shell();
    if (s && s.classList.contains('is-drawer')) {
      e.preventDefault();
      setDrawer(false);
    }
  });

  /* ------------------------------------------------------------------ one click handler */

  doc.addEventListener('click', function (e) {
    var t = e.target;

    // A click outside an open menu closes it (without stealing focus from what was clicked).
    doc.querySelectorAll('details[data-menu][open]').forEach(function (menu) {
      if (!menu.contains(t)) closeMenu(menu, false);
    });

    var el = t.closest('[data-dialog-open]');
    if (el) {
      if (openDialog(doc.getElementById(el.getAttribute('data-dialog-open')), el)) e.preventDefault();
      return;
    }
    el = t.closest('[data-dialog-close]');
    if (el && el.closest('dialog')) {
      el.closest('dialog').close();
      return;
    }
    // A click on the backdrop lands on the <dialog> itself, outside its box.
    if (t.tagName === 'DIALOG' && t.open) {
      var box = t.getBoundingClientRect();
      if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) t.close();
      return;
    }

    el = t.closest('[data-drawer-open]');
    if (el) { setDrawer(true); return; }
    el = t.closest('[data-drawer-close]');
    if (el) { setDrawer(false); return; }
    el = t.closest('[data-rail-toggle]');
    if (el) { setRail(!shell().classList.contains('is-rail')); return; }

    el = t.closest('[data-toast-close]');
    if (el) { dismissToast(el.closest('[data-toast]')); return; }

    // Flash messages rendered as inline alerts.
    el = t.closest('[data-dismiss]');
    if (el) { el.closest('.alert').remove(); return; }

    // The theme: paint the choice at once, then let the form post it so the server remembers.
    el = t.closest('.themepick button[name="theme"]');
    if (el) {
      if (el.value === 'system') root.removeAttribute('data-theme');
      else root.setAttribute('data-theme', el.value);
      return;
    }

    // Demonstration convenience: fill the sign-in form rather than making someone read two
    // strings off one page and type them into another.
    el = t.closest('[data-fill-email]');
    if (el) {
      var email = doc.querySelector('form [name=email]');
      if (!email) return;
      email.value = el.getAttribute('data-fill-email');
      email.form.querySelector('[name=password]').value = el.getAttribute('data-fill-password');
      email.focus();
      return;
    }

    // The copy button beside a hash (ui/data.html).
    el = t.closest('.q-copy[data-copy]');
    if (el) {
      var button = el;
      copyText(button.getAttribute('data-copy')).then(function () {
        button.classList.add('is-done');
        announce('Copied');
        window.setTimeout(function () { button.classList.remove('is-done'); }, 1500);
      }, function () { announce('Copy failed. Select the text and copy it instead.'); });
      return;
    }

    // The older hash chip: click it to copy its full value. A truncated hash you cannot retrieve
    // in full is not evidence of anything.
    el = t.closest('.hash[data-copy]');
    if (el) {
      var chip = el;
      copyText(chip.getAttribute('data-copy')).then(function () {
        var prev = chip.textContent;
        chip.classList.add('copied');
        chip.textContent = 'copied';
        window.setTimeout(function () { chip.classList.remove('copied'); chip.textContent = prev; }, 1000);
      }, function () {});
    }
  });

  // A link followed inside the drawer closes it, so Back does not return to an open drawer.
  doc.addEventListener('click', function (e) {
    if (e.target.closest('.q-side a') && shell() && shell().classList.contains('is-drawer')) {
      shell().classList.remove('is-drawer');
    }
  });

  /* ------------------------------------------------------------------ forms */

  // Submitting a filter form on change is what makes a toolbar feel like a tool rather than a
  // form: no Apply button to hunt for. Text inputs are excluded: they submit on Enter.
  doc.addEventListener('change', function (e) {
    var el = e.target.closest('[data-autosubmit] select, [data-autosubmit] input[type=date]');
    if (el) el.form.requestSubmit();
  });

  // A button marked data-busy-on-submit shows it is working and cannot be pressed twice; the
  // label stays (ui/buttons.html).
  doc.addEventListener('submit', function (e) {
    var button = e.submitter;
    if (!button || !button.hasAttribute('data-busy-on-submit') || e.defaultPrevented) return;
    window.setTimeout(function () {
      button.setAttribute('aria-busy', 'true');
      button.disabled = true;
    }, 0);
  });

  /* ------------------------------------------------------------------ toasts */

  function dismissToast(toast) {
    if (!toast || toast.classList.contains('is-leaving')) return;
    toast.classList.add('is-leaving');
    window.setTimeout(function () { toast.remove(); }, 200);
  }

  function armToast(toast) {
    var timer = null;
    var start = function () { timer = window.setTimeout(function () { dismissToast(toast); }, 8000); };
    var stop = function () { window.clearTimeout(timer); };
    toast.addEventListener('mouseenter', stop);
    toast.addEventListener('focusin', stop);
    toast.addEventListener('mouseleave', start);
    toast.addEventListener('focusout', start);
    start();
  }

  /* ------------------------------------------------------------------ relative time
   * <time datetime data-relative>: the absolute time stays as the title. */

  var units = [
    ['year', 31536000], ['month', 2592000], ['week', 604800],
    ['day', 86400], ['hour', 3600], ['minute', 60]
  ];
  var rtf = window.Intl && Intl.RelativeTimeFormat ? new Intl.RelativeTimeFormat('en-GB', { numeric: 'auto' }) : null;

  function relative(date) {
    var seconds = Math.round((date.getTime() - Date.now()) / 1000);
    if (Math.abs(seconds) < 45) return seconds <= 0 ? 'just now' : 'in a moment';
    for (var i = 0; i < units.length; i++) {
      var size = units[i][1];
      if (Math.abs(seconds) >= size || units[i][0] === 'minute') {
        var value = Math.round(seconds / size);
        if (rtf) return rtf.format(value, units[i][0]);
        var n = Math.abs(value);
        var word = units[i][0] + (n === 1 ? '' : 's');
        return value < 0 ? n + ' ' + word + ' ago' : 'in ' + n + ' ' + word;
      }
    }
    return '';
  }

  function refreshTimes() {
    doc.querySelectorAll('time[data-relative][datetime]').forEach(function (el) {
      var date = new Date(el.getAttribute('datetime'));
      if (isNaN(date.getTime())) return;
      if (!el.title) el.title = el.textContent.trim();
      el.textContent = relative(date);
    });
  }

  /* ------------------------------------------------------------------ start */

  function start() {
    doc.querySelectorAll('[data-toast]').forEach(armToast);
    refreshTimes();
    window.setInterval(refreshTimes, 60000);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})();
