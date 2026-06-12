(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var btns   = document.querySelectorAll('.tab-btn');
    var panels = document.querySelectorAll('.tab-panel');

    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var target = btn.dataset.target;
        btns.forEach(function (b) { b.classList.remove('active'); });
        panels.forEach(function (p) { p.classList.remove('active'); });
        btn.classList.add('active');
        var panel = document.getElementById(target);
        if (panel) {
          panel.classList.add('active');
          window.scrollTo({ top: document.querySelector('.top-bar').offsetHeight, behavior: 'smooth' });
        }
      });
    });

    document.querySelectorAll('.rbr-fold').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var card = btn.closest('.rbr-card');
        var body = card.querySelector('.card-body');
        var collapsed = card.classList.toggle('rbr-collapsed');
        body.style.display = collapsed ? 'none' : '';
        btn.textContent = collapsed ? '▸' : '▾';
      });
    });

    document.querySelectorAll('.rbr-search').forEach(function (input) {
      input.addEventListener('input', function () {
        var q = input.value.trim().toLowerCase();
        var tableId = input.dataset.table;
        var table = document.getElementById(tableId);
        if (!table) { return; }
        var rows = table.tBodies[0].rows;
        var shown = 0;
        for (var i = 0; i < rows.length; i++) {
          var match = !q || rows[i].textContent.toLowerCase().indexOf(q) !== -1;
          rows[i].style.display = match ? '' : 'none';
          if (match) { shown++; }
        }
        var objName = tableId.replace('rbr-', '');
        var counter = document.getElementById('rbr-shown-' + objName);
        if (counter) { counter.textContent = shown; }
      });
    });

    if (typeof DOMPurify !== 'undefined') {
      document.querySelectorAll('.html-render[data-html]').forEach(function (el) {
        el.innerHTML = DOMPurify.sanitize(el.dataset.html);
      });
    }
  });
})();
