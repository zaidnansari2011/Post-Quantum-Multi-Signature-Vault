(function () {
  'use strict';

  var root = document.documentElement;
  var THEME_KEY = 'qvault-style-tile:theme';
  var FIT_KEY = 'qvault-style-tile:fit';
  var SCREEN_W = 1440;

  function load(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* storage blocked: the page still works */ } }
  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

  /* ------------------------------------------------------------ theme: System / Light / Dark */

  var dark = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function refreshHex() {
    var cs = window.getComputedStyle(root);
    $$('[data-hex]').forEach(function (el) {
      var v = cs.getPropertyValue(el.getAttribute('data-hex')).trim();
      if (/^#[0-9a-f]{3,8}$/i.test(v)) el.textContent = v.toUpperCase();
    });
  }

  function applyTheme(choice, persist) {
    if (choice !== 'light' && choice !== 'dark') choice = 'system';
    if (choice === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', choice);
    $$('input[data-theme-choice]').forEach(function (i) { i.checked = i.value === choice; });
    if (persist) save(THEME_KEY, choice);
    refreshHex();
  }

  applyTheme(load(THEME_KEY) || 'system', false);
  if (dark) {
    var onScheme = function () { refreshHex(); };
    if (dark.addEventListener) dark.addEventListener('change', onScheme);
    else if (dark.addListener) dark.addListener(onScheme);
  }

  /* ------------------------------------------------------------ desktop screens: fit to width or actual size */

  var zoomOK = !!(window.CSS && CSS.supports && CSS.supports('zoom', '0.5'));
  var fitMode = 'actual';

  function applyFit() {
    $$('.frame__scroll').forEach(function (sc) {
      var screen = sc.firstElementChild;
      if (!screen) return;
      var z = 1;
      if (fitMode === 'fit' && zoomOK) z = Math.floor(Math.min(1, sc.clientWidth / SCREEN_W) * 10000) / 10000;
      screen.style.zoom = z < 1 ? String(z) : '';
      // Zoom would thin the 2 px focus ring to 1 device pixel; widen it so it still renders as 2.
      if (z < 1) screen.style.setProperty('--focus-width', Math.ceil(2 / z) + 'px');
      else screen.style.removeProperty('--focus-width');
    });
  }

  function setFit(mode, persist) {
    fitMode = mode === 'fit' && zoomOK ? 'fit' : 'actual';
    $$('input[data-fit]').forEach(function (i) { i.checked = i.value === fitMode; });
    if (persist) save(FIT_KEY, fitMode);
    applyFit();
  }

  (function initFit() {
    var first = $('.frame__scroll');
    var stored = load(FIT_KEY);
    var wide = first ? first.clientWidth >= 720 : true;
    if (!zoomOK) $$('[data-fit-control]').forEach(function (el) { el.hidden = true; });
    setFit(stored || (wide ? 'fit' : 'actual'), false);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { applyFit(); });
      $$('.frame__scroll').forEach(function (sc) { ro.observe(sc); });
    } else {
      window.addEventListener('resize', applyFit);
    }
  })();

  /* ------------------------------------------------------------ sticky bar shadow, section highlight */

  var bar = $('.bar');
  var sentinel = document.getElementById('top-sentinel');
  if (bar && sentinel && 'IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      bar.classList.toggle('is-scrolled', !entries[0].isIntersecting);
    }).observe(sentinel);
  }

  var tocLinks = $$('.toc a');
  if (tocLinks.length && 'IntersectionObserver' in window) {
    var byId = {};
    tocLinks.forEach(function (a) { byId[a.getAttribute('href').slice(1)] = a; });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        tocLinks.forEach(function (a) { a.removeAttribute('aria-current'); });
        var link = byId[e.target.id];
        if (link) link.setAttribute('aria-current', 'true');
      });
    }, { rootMargin: '-72px 0px -65% 0px' });
    Object.keys(byId).forEach(function (id) { var s = document.getElementById(id); if (s) spy.observe(s); });
  }

  /* ------------------------------------------------------------ menus and popovers */

  var openPop = null;

  function closePop(returnFocus) {
    if (!openPop) return;
    openPop.panel.hidden = true;
    openPop.trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) openPop.trigger.focus();
    openPop = null;
  }

  function menuItems(panel) {
    return $$('[role="menuitem"], [role="menuitemradio"]', panel).filter(function (el) {
      return el.getAttribute('aria-disabled') !== 'true';
    });
  }

  function firstFocusable(panel) {
    var items = menuItems(panel);
    if (items[0]) return items[0];
    return $('a[href], button:not([disabled]), input:not([disabled])', panel);
  }

  // A popover closes when focus leaves it for somewhere else on the page.
  $$('.pop__panel').forEach(function (panel) {
    panel.addEventListener('focusout', function (e) {
      if (!openPop || openPop.panel !== panel) return;
      var to = e.relatedTarget;
      if (to && !panel.contains(to) && to !== openPop.trigger) closePop(false);
    });
  });

  function togglePop(trigger, byKeyboard) {
    var panel = document.getElementById(trigger.getAttribute('data-pop'));
    if (!panel) return;
    if (openPop && openPop.trigger === trigger) { closePop(false); return; }
    closePop(false);
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    openPop = { trigger: trigger, panel: panel };
    if (byKeyboard) {
      var first = firstFocusable(panel);
      if (first) first.focus();
    }
  }

  /* ------------------------------------------------------------ tabs */

  function initTabs(list) {
    var tabs = $$('[role="tab"]', list);
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute('aria-controls') || '');
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }
    list.addEventListener('click', function (e) {
      var t = e.target.closest('[role="tab"]');
      if (t && list.contains(t)) select(t, false);
    });
    list.addEventListener('keydown', function (e) {
      var i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      var next = null;
      if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
      else if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
      else if (e.key === 'Home') next = tabs[0];
      else if (e.key === 'End') next = tabs[tabs.length - 1];
      if (next) { e.preventDefault(); select(next, true); }
    });
    list.qvSelect = select;
  }
  $$('[role="tablist"]').forEach(initTabs);

  function gotoTab(id) {
    var tab = document.getElementById(id);
    if (!tab) return;
    var list = tab.closest('[role="tablist"]');
    if (list && list.qvSelect) list.qvSelect(tab, true);
  }

  /* ------------------------------------------------------------ copy, with a selection fallback */

  function showFull(scope) {
    var full = $('[data-full]', scope);
    var short = $('[data-short]', scope);
    if (full && short) {
      full.hidden = false;
      short.hidden = true;
      var t = $('[data-expand]', scope);
      if (t) { t.setAttribute('aria-expanded', 'true'); t.textContent = t.getAttribute('data-less'); }
      return full;
    }
    return null;
  }

  function selectText(node) {
    if (!node) return;
    var range = document.createRange();
    range.selectNodeContents(node);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function copyFeedback(btn, ok) {
    var msg = btn.nextElementSibling && btn.nextElementSibling.classList.contains('copy__msg') ? btn.nextElementSibling : null;
    btn.classList.toggle('is-done', ok);
    if (msg) { msg.textContent = ok ? 'Copied' : 'Selected'; msg.classList.toggle('is-sel', !ok); }
    window.clearTimeout(btn.qvTimer);
    btn.qvTimer = window.setTimeout(function () {
      btn.classList.remove('is-done');
      if (msg) msg.textContent = '';
    }, 2000);
  }

  function copyFallback(btn) {
    // The clipboard was refused (common inside an embedded frame). Select the whole value so Ctrl+C
    // works, and never the shortened text with its ellipsis.
    var scope = btn.closest('[data-copy-scope]');
    if (!scope) return;
    var value = btn.getAttribute('data-copy') || '';
    var node = showFull(scope) || $('[data-copy-target]', scope);
    if (!node) return;
    if (node.textContent.replace(/\s+/g, '') !== value.replace(/\s+/g, '')) node.textContent = value;
    selectText(node);
  }

  function writeClipboard(text, onOk, onFail) {
    try {
      navigator.clipboard.writeText(text).then(onOk, onFail);
    } catch (err) {
      onFail();
    }
  }

  function doCopy(btn) {
    var value = btn.getAttribute('data-copy');
    writeClipboard(value,
      function () { copyFeedback(btn, true); },
      function () { copyFallback(btn); copyFeedback(btn, false); });
  }

  function toggleExpand(btn) {
    var scope = btn.closest('[data-copy-scope]') || btn.parentElement;
    var full = $('[data-full]', scope);
    var short = $('[data-short]', scope);
    if (!full || !short) return;
    var expanded = btn.getAttribute('aria-expanded') === 'true';
    full.hidden = expanded;
    short.hidden = !expanded;
    btn.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    btn.textContent = expanded ? btn.getAttribute('data-more') : btn.getAttribute('data-less');
  }

  /* ------------------------------------------------------------ toast */

  var toastEl = document.getElementById('toast');
  var toastTimer = null;
  function toast(text, ms) {
    if (!toastEl) return;
    window.clearTimeout(toastTimer);
    toastEl.classList.remove('is-leaving');
    $('.toast__t', toastEl).textContent = text;
    toastEl.hidden = false;
    toastTimer = window.setTimeout(function () {
      toastEl.classList.add('is-leaving');
      toastTimer = window.setTimeout(function () { toastEl.hidden = true; toastEl.classList.remove('is-leaving'); }, 200);
    }, ms || 5000);
  }

  /* ------------------------------------------------------------ the decision demo: approve and reject */

  var state = 'open';
  var liveEl = document.getElementById('d-live');
  var LIVE = {
    open: '',
    approved: 'You approved. 2 of 2 approvals. The payout is queued.',
    rejected: 'You rejected. Waiting on 1.'
  };

  function closeSeal(marks) {
    marks.forEach(function (m) {
      m.classList.remove('is-closing');
      m.classList.add('is-on');
      void m.offsetWidth;
      m.classList.add('is-closing');
    });
  }

  function setState(next, opts) {
    state = next;
    $$('[data-demo]').forEach(function (el) { el.setAttribute('data-state', next); });
    $$('[data-show]').forEach(function (el) {
      el.hidden = el.getAttribute('data-show').split(' ').indexOf(next) < 0;
    });
    $$('[data-reset-demo]').forEach(function (b) { b.hidden = next === 'open'; });
    var needs = next === 'open' ? '3' : '2';
    $$('[data-needs-count]').forEach(function (el) {
      el.textContent = needs;
      el.setAttribute('aria-label', needs + ' need your signature');
    });
    var closing = $$('[data-closing-mark]');
    closing.forEach(function (m) {
      m.parentElement.setAttribute('aria-label', next === 'approved' ? '2 of 2 approvals' : '1 of 2 approvals');
    });
    if (liveEl) liveEl.textContent = LIVE[next] || '';
    if (next === 'approved') {
      if (opts && opts.animate) closeSeal(closing);
      else closing.forEach(function (m) { m.classList.add('is-on'); });
    } else {
      closing.forEach(function (m) { m.classList.remove('is-on', 'is-closing'); });
    }
    if (next === 'rejected' && opts && opts.reason) {
      $$('[data-reject-reason]').forEach(function (el) { el.textContent = '“' + opts.reason + '”'; });
    }
  }

  function dialogParts(dlg) {
    return {
      form: $('form', dlg),
      submit: $('button[type="submit"]', dlg),
      spinner: $('.spin', dlg),
      cancels: $$('[data-close-dialog]', dlg),
      fields: $$('input, textarea', dlg)
    };
  }

  function setSigning(dlg, on) {
    var p = dialogParts(dlg);
    dlg.qvSigning = on;
    p.submit.setAttribute('aria-busy', on ? 'true' : 'false');
    if (p.spinner) p.spinner.hidden = !on;
    p.cancels.forEach(function (b) { b.disabled = on; });
    p.fields.forEach(function (f) { f.readOnly = on; });
    // The page behind a modal dialog is inert, so the dialog announces its own progress.
    var live = $('[data-dlg-live]', dlg);
    if (live) live.textContent = on ? 'Signing…' : '';
  }

  function showFieldError(input, errEl, on) {
    input.setAttribute('aria-invalid', on ? 'true' : 'false');
    errEl.hidden = !on;
    if (on) input.focus();
  }

  function openDialog(name) {
    var dlg = document.getElementById('dlg-' + name);
    if (!dlg || typeof dlg.showModal !== 'function') return;
    closePop(false);
    if (!dlg.open) dlg.showModal();
    var first = $('[data-initial-focus]', dlg);
    if (first) first.focus();
  }

  $$('dialog.dialog').forEach(function (dlg) {
    dlg.addEventListener('cancel', function (e) { if (dlg.qvSigning) e.preventDefault(); });
    dlg.addEventListener('click', function (e) {
      if (e.target === dlg && !dlg.qvSigning) dlg.close();
    });
  });

  var approveDlg = document.getElementById('dlg-approve');
  if (approveDlg) {
    var apw = $('#dlg-approve-pw', approveDlg);
    var aerr = $('#dlg-approve-pw-err', approveDlg);
    $('form', approveDlg).addEventListener('submit', function (e) {
      e.preventDefault();
      if (approveDlg.qvSigning) return;
      if (!apw.value) { showFieldError(apw, aerr, true); return; }
      showFieldError(apw, aerr, false);
      setSigning(approveDlg, true);
      window.setTimeout(function () {
        setSigning(approveDlg, false);
        approveDlg.close();
        setState('approved', { animate: true });
        var t = document.getElementById('d-title');
        if (t) t.focus({ preventScroll: true });
      }, 1400);
    });
  }

  var rejectDlg = document.getElementById('dlg-reject');
  if (rejectDlg) {
    var reason = $('#dlg-reject-reason', rejectDlg);
    var rerr = $('#dlg-reject-reason-err', rejectDlg);
    var rcount = $('#dlg-reject-count', rejectDlg);
    var rpw = $('#dlg-reject-pw', rejectDlg);
    var rpwerr = $('#dlg-reject-pw-err', rejectDlg);
    reason.addEventListener('input', function () {
      rcount.textContent = reason.value.length + ' / 255';
      if (reason.value.trim()) showFieldError(reason, rerr, false);
    });
    $('form', rejectDlg).addEventListener('submit', function (e) {
      e.preventDefault();
      if (rejectDlg.qvSigning) return;
      if (!reason.value.trim()) { showFieldError(reason, rerr, true); return; }
      if (!rpw.value) { showFieldError(rpw, rpwerr, true); return; }
      showFieldError(rpw, rpwerr, false);
      setSigning(rejectDlg, true);
      window.setTimeout(function () {
        setSigning(rejectDlg, false);
        rejectDlg.close();
        setState('rejected', { reason: reason.value.trim() });
        var t = document.getElementById('d-title');
        if (t) t.focus({ preventScroll: true });
      }, 1400);
    });
  }

  function resetDemo() {
    setState('open');
    if (rejectDlg) {
      var r = $('#dlg-reject-reason', rejectDlg);
      r.value = '';
      $('#dlg-reject-count', rejectDlg).textContent = '0 / 255';
      showFieldError(r, $('#dlg-reject-reason-err', rejectDlg), false);
      r.blur();
    }
  }

  /* ------------------------------------------------------------ small demos: the seal closing, the mark arriving */

  function replaySeal(btn) {
    var target = document.getElementById(btn.getAttribute('data-replay-seal'));
    if (!target) return;
    var marks = $$('.mark', target);
    closeSeal(marks.slice(-1));
  }

  function playMark(btn) {
    var target = document.getElementById(btn.getAttribute('data-play-mark'));
    if (!target) return;
    var disc = $('.mk__arrive', target);
    if (disc) disc.style.transition = 'none';
    target.classList.remove('is-playing');
    void target.getBoundingClientRect();
    if (disc) disc.style.transition = '';
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { target.classList.add('is-playing'); });
    });
  }

  /* ------------------------------------------------------------ one click handler for the page */

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (!(t instanceof Element)) return;

    var popTrigger = t.closest('[data-pop]');
    if (popTrigger) { togglePop(popTrigger, e.detail === 0); return; }
    if (openPop && !openPop.panel.contains(t)) closePop(false);

    var inert = t.closest('a[href="#"]');
    if (inert) e.preventDefault();

    var c = t.closest('[data-copy]');
    if (c) { doCopy(c); return; }

    var x = t.closest('[data-expand]');
    if (x) { toggleExpand(x); return; }

    var od = t.closest('[data-open-dialog]');
    if (od) { e.preventDefault(); openDialog(od.getAttribute('data-open-dialog')); return; }

    var cd = t.closest('[data-close-dialog]');
    if (cd) { var d = cd.closest('dialog'); if (d && !d.qvSigning) d.close(); return; }

    var gt = t.closest('[data-goto-tab]');
    if (gt) { gotoTab(gt.getAttribute('data-goto-tab')); return; }

    var rs = t.closest('[data-replay-seal]');
    if (rs) { replaySeal(rs); return; }

    var pm = t.closest('[data-play-mark]');
    if (pm) { playMark(pm); return; }

    var rd = t.closest('[data-reset-demo]');
    if (rd) { resetDemo(); return; }

    var act = t.closest('[data-action]');
    if (act) {
      var name = act.getAttribute('data-action');
      if (name === 'copy-link') {
        var url = act.getAttribute('data-url');
        closePop(false);
        writeClipboard(url, function () { toast('Link copied'); }, function () { toast('Copy this link: ' + url, 9000); selectText($('.toast__t', toastEl)); });
      } else if (name === 'toast') {
        toast(act.getAttribute('data-text') || 'Link copied');
      } else if (name === 'evidence') {
        closePop(false);
        gotoTab('d-tab-technical');
      }
      return;
    }

    var mi = t.closest('[role="menuitem"], [role="menuitemradio"], a.menu__i, a.notif__i, .notif__ft a');
    if (mi && openPop && openPop.panel.contains(mi) && mi.getAttribute('aria-disabled') !== 'true') closePop(false);
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.matches && t.matches('input[data-theme-choice]')) applyTheme(t.value, true);
    else if (t.matches && t.matches('input[data-fit]')) setFit(t.value, true);
  });

  /* Tooltips (WCAG 1.4.13): Escape hides the one showing without moving focus or the pointer. */
  function clearTipOff() {
    $$('.tip-off').forEach(function (el) {
      if (!el.matches(':hover') && el !== document.activeElement) el.classList.remove('tip-off');
    });
  }
  document.addEventListener('pointerover', clearTipOff);
  document.addEventListener('focusin', clearTipOff);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      var tips = $$('[data-tip]').filter(function (el) { return el.matches(':hover') || el === document.activeElement; });
      tips.forEach(function (el) { el.classList.add('tip-off'); });
    }
    if (e.key === 'Tab' && openPop && openPop.panel.getAttribute('role') === 'menu') { closePop(false); return; }
    if (e.key === 'Escape' && openPop) { closePop(true); return; }
    if (!openPop || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
    var items = menuItems(openPop.panel);
    if (!items.length) return;
    var i = items.indexOf(document.activeElement);
    e.preventDefault();
    var n = e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
    items[n].focus();
  });

  setState('open');
})();
