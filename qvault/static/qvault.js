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

  // A read-only field holding something to copy (a public link) selects itself on focus, so one
  // click and Ctrl+C is enough. focusin, not focus, because only focusin bubbles to a delegated
  // listener.
  doc.addEventListener('focusin', function (e) {
    var el = e.target;
    if (el.matches && el.matches('input[data-select-on-focus], textarea[data-select-on-focus]')) el.select();
  });

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

  // Only a short confirmation is ever a toast (_flash.html keeps anything longer, or marked
  // persist, inline), so eight seconds is enough to read it; hover or focus pauses the timer.
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

  /* ------------------------------------------------------------------ the due field
   * [data-due-field] (ui/forms.html, due_field): a text input holding "YYYY-MM-DD HH:MM" in UTC.
   * The calendar button opens a month grid and a time list that write that input; the moment is
   * read back in words under the field and in any [data-due-echo] (the "who approves" preview).
   * Without this script the input is still a text field the form reads. */

  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December'];
  var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // The typed value as a UTC instant, or null. Accepts the form's two formats.
  function parseDue(text) {
    var m = /^\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})\s*$/.exec(text || '');
    if (!m) return null;
    var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
    if (d.getUTCMonth() !== +m[2] - 1 || +m[4] > 23 || +m[5] > 59) return null;
    return d;
  }

  function formatDue(d) {
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) +
      ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
  }

  function dayStart(d) { return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()); }

  // "Tue 13 Oct 2026, 17:00 UTC, in 7 days": the same words the server writes (ui.due).
  function describeDue(d) {
    var words = DAYS[d.getUTCDay()] + ' ' + d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()].slice(0, 3) +
      ' ' + d.getUTCFullYear() + ', ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ' UTC';
    var left = d.getTime() - Date.now();
    if (left <= 0) return words + ', which has already passed.';
    var hours = Math.floor(left / 3600000);
    var span = hours < 1 ? Math.max(1, Math.floor(left / 60000)) + ' minutes'
      : hours < 48 ? hours + (hours === 1 ? ' hour' : ' hours')
      : Math.floor(hours / 24) + ' days';
    return words + ', in ' + span + '.';
  }

  function dueBounds(field) {
    var min = field.getAttribute('data-min');
    var max = field.getAttribute('data-max');
    return { min: min ? new Date(min) : null, max: max ? new Date(max) : null };
  }

  function readBack(field) {
    var input = field.querySelector('.q-date__in');
    var d = parseDue(input.value);
    var empty = field.getAttribute('data-empty') || '';
    var text = input.value.trim() === '' ? empty : d ? describeDue(d) : 'Type it as 2026-10-13 17:00.';
    var out = field.querySelector('[data-due-read]');
    if (out) out.textContent = text;
    doc.querySelectorAll('[data-due-echo="' + input.id + '"]').forEach(function (echo) {
      echo.textContent = text;
    });
  }

  function buildCalendar(field, month) {
    var pop = field.querySelector('[data-due-pop]');
    var input = field.querySelector('.q-date__in');
    var chosen = parseDue(input.value);
    var bounds = dueBounds(field);
    var today = new Date();
    var first = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
    var days = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 0)).getUTCDate();
    var minDay = bounds.min ? dayStart(bounds.min) : null;
    var maxDay = bounds.max ? dayStart(bounds.max) : null;
    var html = '<div class="q-cal__hd"><span class="q-cal__m" aria-live="polite">' +
      MONTHS[first.getUTCMonth()] + ' ' + first.getUTCFullYear() + '</span><span class="q-cal__nav">' +
      '<button class="q-ib" type="button" data-cal-step="-1" aria-label="Previous month"' +
      (minDay !== null && first.getTime() <= minDay ? ' disabled' : '') + '>' + chevron('left') + '</button>' +
      '<button class="q-ib" type="button" data-cal-step="1" aria-label="Next month"' +
      (maxDay !== null && Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1) > maxDay ? ' disabled' : '') +
      '>' + chevron('right') + '</button></span></div><div class="q-cal__grid" role="group" aria-label="' +
      MONTHS[first.getUTCMonth()] + ' ' + first.getUTCFullYear() + '">';
    // Weeks start on Monday, as UK calendars do.
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach(function (w) {
      html += '<span class="q-cal__wd" aria-hidden="true">' + w.slice(0, 2) + '</span>';
    });
    var lead = (first.getUTCDay() + 6) % 7;
    for (var i = 0; i < lead; i++) html += '<span class="q-cal__d is-out" aria-hidden="true"></span>';
    for (var day = 1; day <= days; day++) {
      var at = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), day);
      var date = new Date(at);
      var off = (minDay !== null && at < minDay) || (maxDay !== null && at > maxDay);
      var picked = chosen && dayStart(chosen) === at;
      html += '<button class="q-cal__d' + (at === dayStart(today) ? ' is-today' : '') + '" type="button" data-cal-day="' +
        at + '" aria-pressed="' + (picked ? 'true' : 'false') + '" aria-label="' + DAY_NAMES[date.getUTCDay()] + ' ' +
        day + ' ' + MONTHS[date.getUTCMonth()] + ' ' + date.getUTCFullYear() + '"' + (off ? ' disabled' : '') +
        ' tabindex="-1">' + day + '</button>';
    }
    html += '</div><div class="q-cal__time"><label for="' + input.id + '-time">Time, UTC</label>' +
      '<span class="q-selwrap"><select class="q-select" id="' + input.id + '-time" data-cal-time>';
    var current = chosen ? pad(chosen.getUTCHours()) + ':' + pad(chosen.getUTCMinutes()) : '17:00';
    var listed = false;
    for (var t = 0; t < 48; t++) {
      var value = pad(Math.floor(t / 2)) + ':' + (t % 2 ? '30' : '00');
      if (value === current) listed = true;
      html += '<option' + (value === current ? ' selected' : '') + '>' + value + '</option>';
    }
    if (!listed) html = html.replace('<select class="q-select" id="' + input.id + '-time" data-cal-time>',
      '<select class="q-select" id="' + input.id + '-time" data-cal-time><option selected>' + current + '</option>');
    html += '</select>' + chevron('down') + '</span></div><div class="q-cal__ft">' +
      '<button class="q-btn q-btn--ghost q-btn--sm" type="button" data-cal-clear>Clear</button>' +
      '<button class="q-btn q-btn--secondary q-btn--sm" type="button" data-cal-done>Done</button></div>';
    pop.innerHTML = html;
    pop.setAttribute('data-month', first.getTime());
    // One day in the tab order: the chosen one, else today or the first that can be picked.
    var focusable = pop.querySelector('.q-cal__d[aria-pressed="true"]:not(:disabled)') ||
      pop.querySelector('.q-cal__d.is-today:not(:disabled)') || pop.querySelector('.q-cal__d[data-cal-day]:not(:disabled)');
    if (focusable) focusable.tabIndex = 0;
    return focusable;
  }

  function chevron(way) {
    var paths = { left: 'M9.75 4.5 6.25 8l3.5 3.5', right: 'M6.25 4.5 9.75 8l-3.5 3.5', down: 'M4.5 6.25 8 9.75l3.5-3.5' };
    return '<svg class="q-icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false"><path d="' +
      paths[way] + '"/></svg>';
  }

  function openDue(field) {
    var pop = field.querySelector('[data-due-pop]');
    var button = field.querySelector('[data-due-open]');
    var chosen = parseDue(field.querySelector('.q-date__in').value);
    var bounds = dueBounds(field);
    var base = chosen || bounds.min || new Date();
    var day = buildCalendar(field, base);
    pop.classList.remove('is-up');
    pop.hidden = false;
    // Open upwards when the calendar would run off the bottom of the window and fits above.
    var box = pop.getBoundingClientRect();
    var input = field.querySelector('.q-date__in').getBoundingClientRect();
    if (box.bottom > window.innerHeight && input.top > box.height + 8) pop.classList.add('is-up');
    button.setAttribute('aria-expanded', 'true');
    if (day) day.focus();
  }

  function closeDue(field, refocus) {
    var pop = field.querySelector('[data-due-pop]');
    if (pop.hidden) return;
    pop.hidden = true;
    field.querySelector('[data-due-open]').setAttribute('aria-expanded', 'false');
    if (refocus) field.querySelector('[data-due-open]').focus();
  }

  function setDue(field, dayAt) {
    var pop = field.querySelector('[data-due-pop]');
    var input = field.querySelector('.q-date__in');
    var time = (pop.querySelector('[data-cal-time]') || {}).value || '17:00';
    var parts = time.split(':');
    var day = new Date(dayAt);
    var moment = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), +parts[0], +parts[1]));
    var bounds = dueBounds(field);
    // A day that is today can still be past at the chosen time; never write a moment before min.
    if (bounds.min && moment < bounds.min) {
      moment = new Date(Math.ceil((bounds.min.getTime() + 60000) / 1800000) * 1800000);
    }
    if (bounds.max && moment > bounds.max) moment = bounds.max;
    input.value = formatDue(moment);
    readBack(field);
  }

  doc.addEventListener('click', function (e) {
    var t = e.target;
    doc.querySelectorAll('[data-due-field]').forEach(function (field) {
      if (!field.contains(t)) closeDue(field, false);
    });
    var field = t.closest('[data-due-field]');
    if (!field) return;
    if (t.closest('[data-due-open]')) {
      if (field.querySelector('[data-due-pop]').hidden) openDue(field); else closeDue(field, true);
      return;
    }
    var step = t.closest('[data-cal-step]');
    if (step && !step.disabled) {
      var pop = field.querySelector('[data-due-pop]');
      var month = new Date(+pop.getAttribute('data-month'));
      month.setUTCMonth(month.getUTCMonth() + (+step.getAttribute('data-cal-step')));
      buildCalendar(field, month);
      var again = pop.querySelector('[data-cal-step="' + step.getAttribute('data-cal-step') + '"]');
      if (again && !again.disabled) again.focus();
      else { var d = pop.querySelector('.q-cal__d[tabindex="0"]'); if (d) d.focus(); }
      return;
    }
    var dayButton = t.closest('[data-cal-day]');
    if (dayButton && !dayButton.disabled) {
      setDue(field, +dayButton.getAttribute('data-cal-day'));
      var at = +dayButton.getAttribute('data-cal-day');
      buildCalendar(field, new Date(at));
      var same = field.querySelector('[data-cal-day="' + at + '"]');
      if (same) same.focus();
      return;
    }
    if (t.closest('[data-cal-clear]')) {
      field.querySelector('.q-date__in').value = '';
      readBack(field);
      closeDue(field, true);
      return;
    }
    if (t.closest('[data-cal-done]')) closeDue(field, true);
  });

  doc.addEventListener('change', function (e) {
    var select = e.target.closest('[data-cal-time]');
    if (!select) return;
    var field = select.closest('[data-due-field]');
    var picked = field.querySelector('.q-cal__d[aria-pressed="true"]');
    if (picked) setDue(field, +picked.getAttribute('data-cal-day'));
  });

  doc.addEventListener('input', function (e) {
    var field = e.target.closest && e.target.closest('[data-due-field]');
    if (field && e.target.classList.contains('q-date__in')) readBack(field);
  });

  doc.addEventListener('keydown', function (e) {
    var field = e.target.closest && e.target.closest('[data-due-field]');
    if (!field) return;
    var pop = field.querySelector('[data-due-pop]');
    if (e.key === 'Escape' && !pop.hidden) {
      e.preventDefault();
      closeDue(field, true);
      return;
    }
    var day = e.target.closest('[data-cal-day]');
    if (!day) return;
    var moves = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (!(e.key in moves)) return;
    e.preventDefault();
    var target = +day.getAttribute('data-cal-day') + moves[e.key] * 86400000;
    var next = pop.querySelector('[data-cal-day="' + target + '"]');
    if (!next) {
      buildCalendar(field, new Date(target));
      next = pop.querySelector('[data-cal-day="' + target + '"]');
    }
    if (next && !next.disabled) {
      pop.querySelectorAll('.q-cal__d[tabindex="0"]').forEach(function (b) { b.tabIndex = -1; });
      next.tabIndex = 0;
      next.focus();
    }
  });

  /* ------------------------------------------------------------------ the file drop zone
   * [data-drop] (ui/forms.html, file_drop): the real file input stays in the page; this adds
   * dropping a file on the zone and naming the chosen file. */

  function showFile(drop) {
    var input = drop.querySelector('input[type=file]');
    var name = drop.querySelector('[data-drop-name]');
    var act = drop.querySelector('.q-drop__act');
    var file = input.files && input.files[0];
    drop.classList.toggle('is-filled', !!file);
    if (name) {
      name.textContent = file ? file.name + ', ' + (file.size < 1024 ? file.size + ' bytes'
        : file.size < 1048576 ? Math.round(file.size / 1024) + ' KB'
        : (file.size / 1048576).toFixed(1) + ' MB') : '';
    }
    if (act) act.textContent = file ? 'Choose another file' : 'Choose a file';
  }

  doc.addEventListener('change', function (e) {
    var drop = e.target.closest && e.target.closest('[data-drop]');
    if (drop) showFile(drop);
  });

  ['dragenter', 'dragover'].forEach(function (type) {
    doc.addEventListener(type, function (e) {
      var drop = e.target.closest && e.target.closest('[data-drop]');
      if (!drop) return;
      e.preventDefault();
      drop.classList.add('is-over');
    });
  });
  ['dragleave', 'drop'].forEach(function (type) {
    doc.addEventListener(type, function (e) {
      var drop = e.target.closest && e.target.closest('[data-drop]');
      if (!drop) return;
      e.preventDefault();
      drop.classList.remove('is-over');
      if (type === 'drop' && e.dataTransfer && e.dataTransfer.files.length) {
        var input = drop.querySelector('input[type=file]');
        input.files = e.dataTransfer.files;
        showFile(drop);
      }
    });
  });

  /* ------------------------------------------------------------------ start */

  function start() {
    // Toasts are drawn by the server, so they are already in the page at load, when a live region
    // would not announce them. Read them out through #q-live, which is empty until now.
    var toasts = doc.querySelectorAll('[data-toast]');
    var said = Array.prototype.map.call(toasts, function (t) {
      return t.querySelector('.q-toast__m').textContent.trim();
    });
    if (said.length) announce(said.join('. '));
    toasts.forEach(armToast);
    refreshTimes();
    window.setInterval(refreshTimes, 60000);
    doc.querySelectorAll('[data-due-field]').forEach(readBack);
  }

  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start);
  else start();
})();
