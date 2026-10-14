// Shor side by side (admin/shor.html; plan docs/plans/shor-side-by-side.md).
//
// This file computes nothing. Every number it shows arrives from the server, one JSON POST per
// button, computed by qvault/attack/shor_walkthrough.py. It reveals the steps one at a time, draws
// the charts as SVG sized to their box (so text stays at the caption size on a phone), and keeps
// the judge's message as text: it is never parsed as markup.
(function () {
  'use strict';
  var root = document.querySelector('[data-shor]');
  if (!root) return;
  var NS = 'http://www.w3.org/2000/svg';
  var csrf = root.getAttribute('data-csrf');
  var urls = {
    start: root.getAttribute('data-url-new'),
    base: root.getAttribute('data-url-base'),
    measure: root.getAttribute('data-url-measure'),
    forge: root.getAttribute('data-url-forge'),
    brute: root.getAttribute('data-url-brute')
  };

  // ------------------------------------------------------------------ small helpers

  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().catch(function () {
        return { ok: false, error: r.status === 429
          ? 'Too many requests from this address. Wait a few minutes and try again.'
          : 'The server did not answer (' + r.status + ').' };
      }).then(function (data) {
        if (!r.ok || !data.ok) throw new Error(data.error || 'The server did not answer (' + r.status + ').');
        return data;
      });
    });
  }

  function fmt(n) { return typeof n === 'number' ? n.toLocaleString('en-GB') : String(n); }
  function pct(p) {
    var v = p * 100;
    if (v >= 0.1) return v.toFixed(2) + '%';
    if (v >= 0.0001) return v.toPrecision(2) + '%';
    return v.toExponential(1) + '%';
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function add(parent, child) { parent.appendChild(child); return child; }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function s(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    for (var k in attrs) if (Object.prototype.hasOwnProperty.call(attrs, k)) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function stext(parent, x, y, text, cls, anchor) {
    var t = s('text', { x: x, y: y, 'class': cls || 'q-shor__axis', 'text-anchor': anchor || 'start' }, parent);
    t.textContent = text;
    return t;
  }
  function field(scope, name) { return scope.querySelector('[data-f="' + name + '"]'); }
  function setText(scope, name, text) { var n = field(scope, name); if (n) n.textContent = text; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function line(parent, text, cls) { return add(parent, el('p', cls, text)); }
  function sup(base, exp) {
    var span = el('span');
    span.appendChild(document.createTextNode(base));
    span.appendChild(el('sup', null, exp));
    return span;
  }
  function table(caption, heads, rows, numeric) {
    var wrap = el('div', 'q-table-wrap q-shor__tw');
    var t = add(wrap, el('table', 'q-table q-table--compact'));
    if (caption) add(t, el('caption', 'q-shor__cap', caption));
    var tr = add(add(t, el('thead')), el('tr'));
    heads.forEach(function (h, i) {
      var th = add(tr, el('th', numeric && numeric[i] ? 'is-num' : null, h));
      th.scope = 'col';
    });
    var body = add(t, el('tbody'));
    rows.forEach(function (row) {
      var r = add(body, el('tr'));
      if (row.strong) r.className = 'q-shor__pick';
      row.cells.forEach(function (c, i) {
        var td = add(r, el('td', numeric && numeric[i] ? 'is-num' : null));
        if (c instanceof Node) td.appendChild(c); else td.textContent = c;
      });
    });
    return wrap;
  }
  function badge(text, tone) { return el('span', 'q-badge q-badge--' + tone, text); }

  // ------------------------------------------------------------------ steps

  function Steps(col) {
    this.items = Array.prototype.slice.call(root.querySelectorAll('[data-steps="' + col + '"] > [data-step]'));
    this.shown = 0;
  }
  Steps.prototype.hideAll = function () {
    this.items.forEach(function (li) { li.hidden = true; });
    this.shown = 0;
  };
  Steps.prototype.showTo = function (n, scroll) {
    this.items.forEach(function (li) { li.hidden = Number(li.getAttribute('data-step')) > n; });
    this.shown = n;
    var target = this.items[n - 1];
    if (scroll && target) target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    drawVisibleCharts();
  };
  Steps.prototype.item = function (n) { return this.items[n - 1]; };

  // ------------------------------------------------------------------ charts

  var charts = {};  // name -> draw function, redrawn when visible and on resize

  function mount(name) { return root.querySelector('[data-chart="' + name + '"]'); }
  function visible(node) { return node && node.offsetParent !== null && node.clientWidth > 0; }
  function canvas(node, height) {
    var w = Math.max(260, Math.floor(node.clientWidth));
    clear(node);
    var svg = s('svg', { viewBox: '0 0 ' + w + ' ' + height, width: w, height: height, 'aria-hidden': 'true', focusable: 'false' }, node);
    return { svg: svg, w: w, h: height };
  }
  function drawVisibleCharts() {
    Object.keys(charts).forEach(function (name) {
      var node = mount(name);
      if (visible(node)) charts[name](node);
    });
  }
  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(drawVisibleCharts, 150);
  });

  function sequenceChart(pic) {
    return function (node) {
      var c = canvas(node, 170);
      var L = 40, R = 8, T = 18, B = 24;
      var n = pic.values.length;
      var X = function (x) { return L + (x / Math.max(1, n - 1)) * (c.w - L - R); };
      var Y = function (v) { return c.h - B - (v / pic.n) * (c.h - T - B); };
      [0, Math.round(pic.n / 2), pic.n].forEach(function (v) {
        s('line', { x1: L, x2: c.w - R, y1: Y(v), y2: Y(v), 'class': 'q-shor__grid' }, c.svg);
        stext(c.svg, L - 6, Y(v) + 4, fmt(v), 'q-shor__axis', 'end');
      });
      stext(c.svg, L, 12, 'f(x) = ' + pic.a + '^x mod ' + pic.n, 'q-shor__axis');
      pic.ones.forEach(function (x, i) {
        s('line', { x1: X(x), x2: X(x), y1: T, y2: c.h - B, 'class': 'q-shor__period' }, c.svg);
        if (i > 0) stext(c.svg, X(x) + 3, T + 10, i === 1 ? 'r = ' + x : i + 'r = ' + x, 'q-shor__lbl q-shor__lbl--strong');
      });
      var d = pic.values.map(function (v, x) { return (x ? 'L' : 'M') + X(x).toFixed(1) + ',' + Y(v).toFixed(1); }).join('');
      s('path', { d: d, 'class': 'q-shor__seqline' }, c.svg);
      var dots = n <= 260;
      pic.values.forEach(function (v, x) {
        if (v === 1 || dots) s('circle', { cx: X(x), cy: Y(v), r: v === 1 ? 3 : 1.6, 'class': v === 1 ? 'q-shor__dot q-shor__dot--one' : 'q-shor__dot' }, c.svg);
      });
      [0, n - 1].forEach(function (x) { stext(c.svg, X(x), c.h - 8, 'x = ' + x, 'q-shor__axis', x ? 'end' : 'start'); });
    };
  }

  function distChart(series, size, maxP, title, hits) {
    return function (node) {
      var c = canvas(node, title.zoom ? 130 : 180);
      var L = 8, R = 8, T = 20, B = 30;
      var span = series.end - series.start;
      var X = function (y) { return L + ((y - series.start) / span) * (c.w - L - R); };
      var Y = function (p) { return c.h - B - (p / maxP) * (c.h - T - B); };
      stext(c.svg, L, 12, title.text, 'q-shor__axis');
      s('line', { x1: L, x2: c.w - R, y1: c.h - B, y2: c.h - B, 'class': 'q-shor__base' }, c.svg);
      var d = '';
      series.values.forEach(function (p, i) {
        if (p <= 0) return;
        var x = X(series.start + (i + 0.5) * series.width).toFixed(1);
        d += 'M' + x + ',' + (c.h - B) + 'V' + Y(p).toFixed(1);
      });
      s('path', { d: d, 'class': 'q-shor__bar' }, c.svg);
      [0, 0.5, 1].forEach(function (f) {
        var y = Math.round(series.start + f * span);
        stext(c.svg, X(y), c.h - 6, fmt(y), 'q-shor__axis', f === 0 ? 'start' : f === 1 ? 'end' : 'middle');
      });
      hits.forEach(function (h) {
        if (h.y < series.start || h.y >= series.end) return;
        var x = X(h.y);
        s('line', { x1: x, x2: x, y1: T, y2: c.h - B, 'class': 'q-shor__hitline' }, c.svg);
        s('path', { d: 'M' + x + ',' + (c.h - B + 2) + 'l-4,7h8z', 'class': 'q-shor__hit' }, c.svg);
      });
    };
  }

  function scalingChart(data) {
    return function (node) {
      var c = canvas(node, node.clientWidth < 480 ? 260 : 300);
      var L = 44, R = 12, T = 12, B = 40;
      var lx0 = Math.log2(256), lx1 = Math.log2(32768);
      var X = function (x) { return L + ((Math.log2(x) - lx0) / (lx1 - lx0)) * (c.w - L - R); };
      var Y = function (y) { return c.h - B - (y / 300) * (c.h - T - B); };
      for (var v = 0; v <= 300; v += 50) {
        s('line', { x1: L, x2: c.w - R, y1: Y(v), y2: Y(v), 'class': 'q-shor__grid' }, c.svg);
        var t = stext(c.svg, L - 6, Y(v) + 4, '2', 'q-shor__axis', 'end');
        var sp = s('tspan', { dy: -5, 'class': 'q-shor__axis' }, t);
        sp.textContent = String(v);
        t.appendChild(sp);
      }
      [512, 2048, 8192, 32768].forEach(function (x) {
        s('line', { x1: X(x), x2: X(x), y1: c.h - B, y2: c.h - B + 4, 'class': 'q-shor__tick' }, c.svg);
        stext(c.svg, X(x), c.h - B + 16, fmt(x), 'q-shor__axis', x === 32768 ? 'end' : 'middle');
      });
      stext(c.svg, (L + c.w - R) / 2, c.h - 4, 'Public key size, bits (log scale)', 'q-shor__axis', 'middle');
      data.forEach(function (series) {
        var d = series.points.map(function (p, i) { return (i ? 'L' : 'M') + X(p.x).toFixed(1) + ',' + Y(p.y).toFixed(1); }).join('');
        s('path', { d: d, 'class': 'q-shor__line q-shor__line--' + series.id }, c.svg);
        series.points.forEach(function (p) {
          var dot = s('circle', { cx: X(p.x), cy: Y(p.y), r: 3, 'class': 'q-shor__pt q-shor__pt--' + series.id }, c.svg);
          var title = s('title', {}, dot);
          title.textContent = series.label + (p.label ? ' (' + p.label + ')' : '') + ': ' + fmt(p.x) + ' bits, about 2^' + p.y;
        });
      });
    };
  }

  function legend(data) {
    var box = el('div', 'q-shor__legend');
    data.forEach(function (series) {
      var item = add(box, el('span', 'q-shor__key-i'));
      var sw = s('svg', { viewBox: '0 0 28 10', width: 28, height: 10, 'aria-hidden': 'true' }, item);
      s('line', { x1: 1, x2: 27, y1: 5, y2: 5, 'class': 'q-shor__line q-shor__line--' + series.id }, sw);
      add(item, el('span', null, series.label));
    });
    return box;
  }

  var scaling = root.querySelector('[data-scaling]');
  if (scaling) {
    var scaleData = JSON.parse(scaling.textContent);
    var scaleMount = mount('scaling');
    scaleMount.parentNode.insertBefore(legend(scaleData), scaleMount);
    charts.scaling = scalingChart(scaleData);
  }

  // ------------------------------------------------------------------ the RSA column

  var rsa = new Steps('rsa');
  rsa.hideAll();
  var startForm = root.querySelector('[data-rsa-start]');
  var statusLine = root.querySelector('[data-rsa-status]');
  var nextRsa = root.querySelector('[data-next="rsa"]');
  var allRsa = root.querySelector('[data-runall="rsa"]');
  var measureBtn = root.querySelector('[data-rsa-measure]');
  var verdict = root.querySelector('[data-rsa-verdict]');
  var S = null;  // the current run

  function status(text) { statusLine.textContent = text || ''; }
  function setBusy(on) {
    if (S) S.busy = on;
    [nextRsa, measureBtn].forEach(function (b) { if (b) b.disabled = on || !S; });
    allRsa.disabled = on;
    startForm.querySelector('button').disabled = on;
    if (!on) labelNext();
  }
  function labelNext() {
    if (!S) return;
    var label = nextRsa.querySelector('span') || nextRsa;
    if (S.needBase) label.textContent = 'Draw a new base';
    else if (rsa.shown >= 9) label.textContent = 'Done';
    else label.textContent = 'Next step';
    nextRsa.disabled = rsa.shown >= 9 && !S.needBase;
    allRsa.disabled = rsa.shown >= 9;
  }
  function message() { return startForm.querySelector('input[name="message"]').value; }

  function renderBase(d) {
    var s2 = rsa.item(2), s3 = rsa.item(3), s4 = rsa.item(4);
    setText(s2, 'a', d.base.a);
    setText(s2, 'base-number', d.base_number === 1 ? 'First base for this key' : 'Base ' + d.base_number + ' for this key');
    var red = d.base.redrawn;
    setText(s2, 'redrawn', red.length
      ? 'Redrawn first: ' + red.map(function (b) { return 'a = ' + b.a + ' (gcd ' + b.gcd + ')'; }).join(', ') +
        '. A base sharing a factor with N would factor it with no quantum step. That only happens at toy sizes (about 2^-1013 of the time for RSA-2048), so such a base is redrawn and counted, not used.'
      : '');

    var pic = d.picture;
    var seq = clear(field(s3, 'sequence'));
    pic.values.forEach(function (v, x) {
      var cell = add(seq, el('span'));
      add(cell, el(v === 1 ? 'b' : 'span', null, String(v)));
      add(cell, el('i', null, 'x=' + x));
    });
    setText(s3, 'period-note',
      'f returns to 1 at x = ' + pic.ones.join(', ') + ', so its period is r = ' + pic.r + '. ' +
      'This picture is computed classically, which only works because N is tiny: at 2048 bits the sequence can run for about 2^2048 steps before it repeats. ' +
      'The attack below does not use it. It learns r from a measurement.' +
      (pic.truncated ? ' Showing the first ' + pic.values.length + ' values.' : ''));
    charts.sequence = sequenceChart(pic);

    var reg = d.register;
    setText(s4, 't', reg.t + ' (2 x ' + (reg.qubits - reg.t) + ' bits of N)');
    setText(s4, 'size', fmt(reg.size));
    setText(s4, 'qubits', fmt(reg.qubits) + ' (t plus ' + (reg.qubits - reg.t) + ' for the value register)');
    setText(s4, 'held', fmt(reg.held) + ' complex numbers');
    setText(s4, 'observed', 'a^x mod N = ' + reg.observed + '. Only the x that give ' + reg.observed + ' remain, every r-th one.');
    setText(s4, 'dist-note',
      fmt(reg.peak_count) + ' peaks, found as local maxima of the distribution; together they hold ' + pct(reg.peak_mass) +
      ' of the probability (counting each peak and its two neighbours). They sit at multiples of Q/r = ' + fmt(reg.size) + '/' + pic.r +
      ' = ' + (reg.size / pic.r).toFixed(1) + '. Built and transformed in ' + fmt(reg.elapsed_ms) + ' ms on this server.');
    S.register = reg;
    drawDist();
  }

  function drawDist() {
    var reg = S.register;
    var hits = S.shots.map(function (x) { return x.sample; });
    charts.dist = distChart(reg.buckets, reg.size, reg.max_p, { text: 'Chance of each y, out of Q = ' + fmt(reg.size) + ' (tallest ' + pct(reg.max_p) + ')' }, hits);
    if (reg.zoom) {
      charts.zoom = distChart(reg.zoom, reg.size, reg.max_p, { text: 'The first peaks, magnified: y from 0 to ' + fmt(reg.zoom.end), zoom: true }, hits);
    } else {
      delete charts.zoom;
      clear(mount('zoom'));
    }
    drawVisibleCharts();
  }

  function resetAfterBase() {
    S.shots = [];
    S.usable = null;
    S.needBase = false;
    clear(field(rsa.item(5), 'shots'));
    setText(rsa.item(5), 'shots-note', '');
    ['factoring', 'private', 'forgery'].forEach(function (f) { clear(field(root, f)); });
  }

  function start() {
    var msg = message();
    setBusy(true);
    status('Generating a key and simulating the register...');
    verdict.hidden = true;
    return post(urls.start, { message: msg }).then(function (d) {
      S = { run: d.run, key: d.key, message: msg, shots: [], usable: null, needBase: false, busy: false };
      resetAfterBase();
      setText(rsa.item(1), 'n', fmt(d.key.n));
      setText(rsa.item(1), 'e', fmt(d.key.e));
      renderBase(d);
      rsa.showTo(1, true);
      status('');
    }).catch(function (err) { status(err.message); })
      .then(function () { setBusy(false); });
  }

  function newBase() {
    status('Drawing a new base and simulating the register again...');
    return post(urls.base, { run: S.run }).then(function (d) {
      resetAfterBase();
      renderBase(d);
      rsa.showTo(4, false);
      rsa.item(2).scrollIntoView({ block: 'start', behavior: 'smooth' });
      status('');
    });
  }

  function measure() {
    return post(urls.measure, { run: S.run }).then(function (d) {
      S.shots.push(d);
      var a = d.analysis;
      var row = add(field(rsa.item(5), 'shots'), el('tr'));
      add(row, el('td', null, String(d.sample.number)));
      add(row, el('td', 'is-num', fmt(d.sample.y)));
      add(row, el('td', 'is-num', pct(d.sample.p)));
      add(row, el('td', null, d.sample.near_peak ? 'Yes' : 'No'));
      add(row, el('td', null, a.usable ? 'r = ' + a.order : 'None'));
      var on = S.shots.filter(function (x) { return x.sample.near_peak; }).length;
      setText(rsa.item(5), 'shots-note', on + ' of ' + S.shots.length + ' measurements landed on a peak (within 1 of it). The peaks hold ' + pct(S.register.peak_mass) + ' of the probability.');
      if (a.usable && !S.usable) S.usable = d;
      drawDist();
      return d;
    });
  }

  function renderAnalysis(d) {
    var a = d.analysis, s6 = rsa.item(6), n = S.key.n;
    setText(s6, 'phase', fmt(a.y) + ' / ' + fmt(a.size) + ' = ' + a.decimal);
    setText(s6, 'terms', '[' + a.terms[0] + '; ' + a.terms.slice(1).join(', ') + ']');
    var body = clear(field(s6, 'convergents'));
    a.convergents.forEach(function (c) {
      var tr = add(body, el('tr'));
      if (c.q === a.chosen) tr.className = 'q-shor__pick';
      add(tr, el('td', 'is-num', fmt(c.p)));
      add(tr, el('td', 'is-num', fmt(c.q)));
      add(tr, el('td', null, c.below_n ? 'Yes' : 'No, too large'));
    });
    setText(s6, 'chosen',
      'The closest fraction to y / Q with a denominator below N = ' + n + ' is ' + a.best.p + '/' + a.best.q +
      ', so the candidate period is ' + a.chosen + '.' +
      (a.chosen_is_convergent ? '' : ' It is not one of the convergents above (a semiconvergent): the measurement was off a peak.'));
    var trail = clear(field(s6, 'trail'));
    a.trail.forEach(function (t) {
      var tr = add(trail, el('tr'));
      if (t.value === 1) tr.className = 'q-shor__pick';
      add(tr, el('td', 'is-num', String(t.multiple)));
      add(tr, el('td', 'is-num', fmt(t.exponent)));
      add(tr, el('td', 'is-num', String(t.value)));
    });
    var note = '';
    if (a.uninformative) {
      note = 'This measurement carried no information (denominator 1). The multiple test found r by trying small exponents directly, which works only because r is small here.';
    } else if (a.order !== a.chosen) {
      note = a.chosen + ' is a proper divisor of the period: the measurement gave s/r with s and r sharing a factor. ' +
        'Testing small multiples finds ' + a.chosen + ' x ' + (a.order / a.chosen) + ' = ' + a.order + ', the first exponent that brings a back to 1. This is the step from Shor\'s paper.';
    } else {
      note = 'a^' + a.order + ' mod N = 1, so r = ' + a.order + '.';
    }
    setText(s6, 'trail-note', note);
  }

  function renderFactoring(d) {
    var f = d.factoring, box = clear(field(root, 'factoring'));
    var calc = add(box, el('div', 'q-shor__calc'));
    if (f.reason === 'odd') {
      line(calc, 'r = ' + f.r + ' is odd, so a^(r/2) is not a whole power. This base cannot be used.');
      line(box, 'This is the real algorithm: it draws a new base and runs the quantum step again. Press Draw a new base.', 'q-note');
      S.needBase = true;
      return;
    }
    line(calc, 'r = ' + f.r + ' is even, so take x = a^(r/2) mod N = ' + f.a + '^' + f.half + ' mod ' + f.n + ' = ' + f.x + '.');
    if (f.reason === 'minus_one') {
      line(calc, 'x = ' + f.x + ' = N - 1, so a^(r/2) = -1 (mod N) and both gcds would be trivial. This base cannot be used.');
      line(box, 'This is the real algorithm: it draws a new base and runs the quantum step again. Press Draw a new base.', 'q-note');
      S.needBase = true;
      return;
    }
    [['x - 1', f.g_minus], ['x + 1', f.g_plus]].forEach(function (pair) {
      var g = pair[1];
      line(box, 'gcd(' + pair[0] + ', N) = gcd(' + (pair[0] === 'x - 1' ? f.x - 1 : f.x + 1) + ', ' + f.n + ') = ' + g.value, 'q-shor__h');
      if (g.steps.length) {
        box.appendChild(table(null, ['Step (x = q * y + r)'], g.steps.map(function (st) {
          return { cells: [st.x + ' = ' + st.q + ' x ' + st.y + ' + ' + st.r] };
        })));
      }
    });
    if (f.ok) {
      var res = add(box, el('div', 'q-shor__calc'));
      line(res, 'N = ' + f.n + ' = ' + Math.min(f.p, f.q) + ' x ' + Math.max(f.p, f.q) + '. Check: ' + f.p + ' x ' + f.q + ' = ' + (f.p * f.q) + '.', 'q-shor__key');
    } else {
      line(box, 'Both gcds were trivial. Press Draw a new base.', 'q-note');
      S.needBase = true;
    }
  }

  function renderPrivate(d) {
    var k = d.key, box = clear(field(root, 'private'));
    var calc = add(box, el('div', 'q-shor__calc'));
    line(calc, 'phi = (p - 1)(q - 1) = ' + (k.p - 1) + ' x ' + (k.q - 1) + ' = ' + fmt(k.phi));
    line(calc, 'lambda = lcm(p - 1, q - 1) = phi / gcd(p - 1, q - 1) = ' + fmt(k.phi) + ' / ' + k.gcd + ' = ' + fmt(k.lambda));
    line(box, 'd is the inverse of e = ' + k.e + ' mod lambda, by the extended Euclidean algorithm. Each row keeps r = s x lambda + t x e.');
    box.appendChild(table(null, ['q', 'r', 's', 't'], k.rows.map(function (r) {
      return { cells: [r.q === null ? '' : String(r.q), String(r.r), String(r.s), String(r.t)], strong: r.r === 1 };
    }), [true, true, true, true]));
    var res = add(box, el('div', 'q-shor__calc'));
    line(res, 'd = ' + k.d + '. Check: e x d mod lambda = ' + k.e + ' x ' + k.d + ' mod ' + k.lambda + ' = ' + ((k.e * k.d) % k.lambda) + '.');
    var reveal = line(res, 'Revealed now, from the key the server generated: p = ' + k.real_p + ', q = ' + k.real_q + ', d = ' + k.real_d + '. ', 'q-shor__key');
    reveal.appendChild(k.match ? badge('Match', 'critical') : badge('No match', 'warning'));
    line(box, 'The key was made with lambda, as RSA keys usually are, so d is computed mod lambda to compare digit for digit. d mod phi would sign just as well.', 'q-note');
  }

  function renderForgery(f) {
    var box = clear(field(root, 'forgery'));
    var calc = add(box, el('div', 'q-shor__calc'));
    var m = line(calc, 'Message: ');
    m.appendChild(el('strong', null, f.message));
    var h = line(calc, 'SHA-256: ');
    h.appendChild(el('span', 'q-mono q-shor__hex', f.digest));
    line(calc, 'As a number, reduced mod N: m = ' + f.m + '.');
    line(calc, 'Signature: s = m^d mod N = ' + f.m + '^' + f.d + ' mod ' + f.n + ' = ' + f.s + '.');
    var v = line(calc, 'The real verifier, ToyRSASignatureProvider.verify, returned ' + (f.valid ? 'True' : 'False') + ': ', 'q-shor__key');
    v.appendChild(f.valid ? badge('Valid', 'critical') : badge('Rejected', 'neutral'));
    line(calc, 'Check: s^e mod N = ' + f.s + '^' + f.e + ' mod ' + f.n + ' = ' + f.s_e_mod_n + (f.s_e_mod_n === f.m ? ' = m.' : '.'));
    var ed = f.edited;
    var p = line(box, 'The same signature on "' + ed.message + '" (m = ' + ed.m + '): verify returned ' + (ed.valid ? 'True' : 'False') + '.', 'q-note');
    if (ed.valid) p.textContent += ' At 9 bits both messages happen to reduce to the same m, a weakness of the toy size, not of the attack.';
    line(box, 'The SHA-256 digest is reduced mod N because the toy modulus is 9 bits. Recovering d forges any message whatever the padding.', 'q-note');
    verdict.hidden = !f.valid;
  }

  function forge(msg) {
    return post(urls.forge, { run: S.run, message: msg }).then(renderForgery);
  }

  function step() {
    if (S.needBase) return newBase();
    var n = rsa.shown;
    if (n < 4) { rsa.showTo(n + 1, true); return Promise.resolve(); }
    if (n === 4) {
      rsa.showTo(5, true);
      return S.shots.length ? Promise.resolve() : measure();
    }
    if (n === 5) {
      var tries = 0;
      var until = function () {
        if (S.usable) { renderAnalysis(S.usable); rsa.showTo(6, true); return Promise.resolve(); }
        if (++tries > 60) return Promise.reject(new Error('No usable measurement in 60 shots. Try a new key.'));
        return measure().then(until);
      };
      return until();
    }
    if (n === 6) { renderFactoring(S.usable); rsa.showTo(7, true); return Promise.resolve(); }
    if (n === 7) { renderPrivate(S.usable); rsa.showTo(8, true); return Promise.resolve(); }
    if (n === 8) { return forge(S.message).then(function () { rsa.showTo(9, true); }); }
    return Promise.resolve();
  }

  function guarded(fn) {
    if (!S || S.busy) return Promise.resolve();
    setBusy(true);
    status('');
    return fn().catch(function (err) { status(err.message); }).then(function () { setBusy(false); });
  }

  startForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (S && S.busy) return;
    start();
  });
  nextRsa.addEventListener('click', function () { guarded(step); });
  measureBtn.addEventListener('click', function () { guarded(measure); });
  allRsa.addEventListener('click', function () {
    var run = function () {
      var go = function () {
        if (rsa.shown >= 9 && !S.needBase) return Promise.resolve();
        return step().then(function () { return sleep(200); }).then(go);
      };
      return go();
    };
    if (!S) { start().then(function () { if (S) guarded(run); }); return; }
    guarded(run);
  });
  allRsa.disabled = false;  // Run all also starts a key if there is none
  root.querySelector('[data-rsa-forge]').addEventListener('submit', function (e) {
    e.preventDefault();
    var input = e.target.querySelector('input[name="message"]');
    guarded(function () { return forge(input.value); });
  });

  // ------------------------------------------------------------------ the ML-DSA column

  var ml = new Steps('mldsa');
  ml.showTo(1, false);
  var nextMl = root.querySelector('[data-next="mldsa"]');
  var allMl = root.querySelector('[data-runall="mldsa"]');
  nextMl.hidden = false;
  allMl.hidden = false;
  function labelMl() {
    var done = ml.shown >= ml.items.length;
    nextMl.disabled = done;
    allMl.disabled = done;
  }
  nextMl.addEventListener('click', function () { ml.showTo(ml.shown + 1, true); labelMl(); });
  allMl.addEventListener('click', function () {
    ml.showTo(ml.items.length, false);
    labelMl();
    runBrute();
  });
  labelMl();

  // Brute force: one POST per slice of work, so the counter is live; the server caps the total.
  var bruteBtn = root.querySelector('[data-brute]');
  var bruteNote = root.querySelector('[data-brute-note]');
  var lweRun = root.getAttribute('data-lwe-run');
  var bruteRunning = false;

  function bruteRow(r) {
    var row = root.querySelector('[data-brute-row="' + r.n + '"]');
    row.querySelector('[data-b="checked"]').textContent = fmt(r.checked);
    row.querySelector('[data-b="time"]').textContent = r.elapsed_s.toFixed(2) + ' s';
    var cell = clear(row.querySelector('[data-b="result"]'));
    if (r.done && r.found) {
      cell.appendChild(document.createTextNode('Found (' + r.found.join(', ') + ') '));
      cell.appendChild(r.match ? badge('Matches s', 'critical') : badge('A different short solution', 'warning'));
    } else if (r.capped) {
      cell.textContent = 'Stopped at the ' + r.cap_s + ' s cap. Full search estimated at ' + fmt(r.estimated_full_s) + ' s.';
    } else {
      cell.textContent = 'Searching';
    }
  }

  function runBrute() {
    if (bruteRunning) return;
    bruteRunning = true;
    bruteBtn.disabled = true;
    var sizes = Array.prototype.map.call(root.querySelectorAll('[data-brute-row]'), function (r) { return Number(r.getAttribute('data-brute-row')); });
    var last = null;
    var one = function (n) {
      return post(urls.brute, { run: lweRun, n: n }).then(function (r) {
        bruteRow(r);
        last = r;
        if (!(r.done || r.capped)) return one(n);
        return r;
      });
    };
    var chain = Promise.resolve();
    sizes.forEach(function (n) { chain = chain.then(function () { return one(n); }); });
    chain.then(function () {
      if (last && last.real_size) {
        var rs = last.real_size;
        bruteNote.textContent = 'At ML-DSA-65\'s size the secret s1 alone has ' + fmt(rs.coefficients) + ' coefficients in [' + rs.range[0] + ', ' + rs.range[1] +
          ']: about 2^' + fmt(rs.log2_candidates) + ' candidates. At the rate measured here (' + fmt(rs.rate_per_s) + ' a second) that is about 10^' + fmt(rs.log10_years) +
          ' years. Estimated, and beside the point: lattice reduction (next step) is far faster than brute force, and still out of reach.';
      }
    }).catch(function (err) { bruteNote.textContent = err.message; })
      .then(function () { bruteRunning = false; });
  }
  bruteBtn.addEventListener('click', runBrute);

  drawVisibleCharts();
})();
