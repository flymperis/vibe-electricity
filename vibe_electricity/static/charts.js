// Shared Chart.js setup: theme colours from CSS variables, Greek number format.
(function () {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();
  const C = {
    accent: v('--accent'), text: v('--text'), muted: v('--muted'), line: v('--line'), panel: v('--panel'),
    c1: v('--c1'), c2: v('--c2'), c3: v('--c3'), c4: v('--c4'), c5: v('--c5'), good: v('--good'), bad: v('--bad'),
  };
  const nf = (d) => new Intl.NumberFormat('el-GR', { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmt = {
    eur: (x) => x == null ? '—' : nf(2).format(x) + ' €',
    eur0: (x) => x == null ? '—' : nf(0).format(x) + ' €',
    kwh: (x) => x == null ? '—' : nf(0).format(x) + ' kWh',
    kwhd: (x) => x == null ? '—' : nf(1).format(x) + ' kWh/ημ.',
    rate: (x) => x == null ? '—' : nf(3).format(x) + ' €/kWh',
    num: (d) => (x) => x == null ? '—' : nf(d).format(x),
  };
  if (window.Chart) {
    Chart.defaults.color = C.muted;
    Chart.defaults.borderColor = C.line;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 12;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.animation.duration = 350;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.boxHeight = 10;
    Chart.defaults.plugins.legend.labels.useBorderRadius = true;
    Chart.defaults.plugins.legend.labels.borderRadius = 3;
    Chart.defaults.plugins.tooltip.backgroundColor = C.text;
    Chart.defaults.plugins.tooltip.titleColor = C.panel;
    Chart.defaults.plugins.tooltip.bodyColor = C.panel;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.interaction = { mode: 'index', intersect: false };
    Chart.defaults.elements.bar.borderRadius = 4;
    Chart.defaults.elements.line.tension = 0.3;
    Chart.defaults.elements.point.radius = 2.5;
    Chart.defaults.elements.point.hoverRadius = 5;
  }
  const small = () => window.matchMedia('(max-width: 760px)').matches;
  window.VE = { C, fmt, small, alpha: (hex, a) => {
    const h = hex.replace('#', ''); const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  } };
})();
