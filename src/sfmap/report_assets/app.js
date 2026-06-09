(function () {
  'use strict';

  const escHtml = str => String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  /* ── Collapsible cards ──────────────────────────────────────── */
  function initCollapse() {
    document.querySelectorAll('.card.collapsible .card-title').forEach(title => {
      title.addEventListener('click', () => {
        title.closest('.card').classList.toggle('collapsed');
      });
    });
  }

  /* ── Row detail dialog ──────────────────────────────────────── */
  function initRowDetails() {
    document.querySelectorAll('table').forEach(table => {
      const headers = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
      table.querySelectorAll('tbody tr').forEach(row => {
        row.setAttribute('tabindex', '0');
        row.setAttribute('role', 'button');
        row.setAttribute('aria-label', 'View record detail');
        const open = () => {
          const cells = [...row.querySelectorAll('td')].map(td => td.textContent.trim());
          openDetail(headers, cells);
        };
        row.addEventListener('click', open);
        row.addEventListener('keydown', e => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
        });
      });
    });
  }

  function openDetail(headers, cells) {
    const dialog = document.getElementById('detail-dialog');
    const body   = document.getElementById('detail-body');
    if (!dialog) return;

    body.innerHTML = '<div class="detail-grid">'
      + headers.map((h, i) => {
          const val     = cells[i] ?? '';
          const isEmpty = val === '' || val === '…';
          return '<div class="detail-kv">'
            + `<span class="detail-key">${escHtml(h)}</span>`
            + `<span class="detail-val${isEmpty ? ' empty' : ''}" data-raw="${escHtml(val)}">`
            + (isEmpty ? 'empty' : escHtml(val))
            + '</span>'
            + '</div>';
        }).join('')
      + '</div>';

    body.querySelectorAll('.detail-val:not(.empty)').forEach(el => {
      el.addEventListener('click', () => copyVal(el.dataset.raw ?? el.textContent));
    });

    dialog.showModal();
  }

  /* ── Copy value ─────────────────────────────────────────────── */
  function copyVal(text) {
    navigator.clipboard?.writeText(text).then(() => {
      const toast = document.getElementById('copy-toast');
      if (!toast) return;
      toast.classList.remove('show');
      void toast.offsetWidth;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 1400);
    });
  }

  /* ── TOC active section ─────────────────────────────────────── */
  function initTOC() {
    const links = [...document.querySelectorAll('.toc a')];
    if (!links.length) return;

    const sections = links.map(a => document.getElementById(a.getAttribute('href').slice(1)));

    const obs = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        links.forEach(a => a.classList.remove('active'));
        const id   = entry.target.id;
        const link = links.find(a => a.getAttribute('href') === `#${id}`);
        link?.classList.add('active');
      }
    }, { threshold: 0.08, rootMargin: '-60px 0px -55% 0px' });

    sections.filter(Boolean).forEach(s => obs.observe(s));
  }

  /* ── Init ───────────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', () => {
    initCollapse();
    initRowDetails();
    initTOC();
  });
})();
