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

    if (typeof DOMPurify !== 'undefined') {
      document.querySelectorAll('.html-render[data-html]').forEach(function (el) {
        el.innerHTML = DOMPurify.sanitize(el.dataset.html);
      });
    }
  });
})();
