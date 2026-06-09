(function () {
  'use strict';

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Collapsible cards ──────────────────────────────────── */
  function initCollapse() {
    document.querySelectorAll('.card.collapsible .card-title').forEach(function (title) {
      title.addEventListener('click', function () {
        title.closest('.card').classList.toggle('collapsed');
      });
    });
  }

  /* ── Row detail panel ───────────────────────────────────── */
  function initRowDetails() {
    document.querySelectorAll('table').forEach(function (table) {
      var headers = Array.from(table.querySelectorAll('thead th')).map(function (th) {
        return th.textContent.trim();
      });
      table.querySelectorAll('tbody tr').forEach(function (row) {
        row.addEventListener('click', function () {
          var cells = Array.from(row.querySelectorAll('td')).map(function (td) {
            return td.textContent.trim();
          });
          openDetail(headers, cells);
        });
      });
    });
  }

  function openDetail(headers, cells) {
    var title = document.getElementById('detail-title');
    var body = document.getElementById('detail-body');

    title.textContent = 'Record Detail';

    var items = headers.map(function (h, i) {
      var val = cells[i] !== undefined ? cells[i] : '';
      var isEmpty = val === '' || val === '…';
      return '<div class="detail-kv">'
        + '<span class="detail-key">' + escHtml(h) + '</span>'
        + '<span class="detail-val' + (isEmpty ? ' empty' : '') + '" data-raw="' + escHtml(val) + '" title="Click to copy">'
        + (isEmpty ? 'empty' : escHtml(val))
        + '</span>'
        + '</div>';
    });

    body.innerHTML = '<div class="detail-grid">' + items.join('') + '</div>';

    body.querySelectorAll('.detail-val:not(.empty)').forEach(function (el) {
      el.addEventListener('click', function () {
        copyVal(el.dataset.raw || el.textContent);
      });
    });

    document.getElementById('detail-overlay').classList.add('open');
    document.getElementById('detail-panel').classList.add('open');
  }

  window.closeDetail = function () {
    document.getElementById('detail-overlay').classList.remove('open');
    document.getElementById('detail-panel').classList.remove('open');
  };

  function copyVal(text) {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(function () {
      var toast = document.getElementById('copy-toast');
      if (!toast) return;
      toast.classList.add('show');
      setTimeout(function () { toast.classList.remove('show'); }, 1400);
    });
  }

  /* ── TOC active section ──────────────────────────────────── */
  function initTOC() {
    var links = Array.from(document.querySelectorAll('.toc a'));
    if (!links.length) return;

    var sections = links.map(function (a) {
      return document.getElementById(a.getAttribute('href').replace('#', ''));
    });

    var active = null;

    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var id = entry.target.id;
          links.forEach(function (a) { a.classList.remove('active'); });
          var link = links.find(function (a) { return a.getAttribute('href') === '#' + id; });
          if (link) {
            link.classList.add('active');
            active = link;
          }
        }
      });
    }, { threshold: 0.08, rootMargin: '-80px 0px -55% 0px' });

    sections.filter(Boolean).forEach(function (s) { obs.observe(s); });
  }

  /* ── Keyboard ────────────────────────────────────────────── */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') window.closeDetail();
  });

  /* ── Init ────────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    initCollapse();
    initRowDetails();
    initTOC();
  });
})();
