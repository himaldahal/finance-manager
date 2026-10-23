// Runs before first paint: marks the page as scripted and restores the sidebar state (no flash).
(function () {
  var root = document.documentElement;
  root.classList.add('js');
  try {
    if (localStorage.getItem('fm:sidebar') === 'collapsed') root.setAttribute('data-sidebar', 'collapsed');
  } catch (e) { /* storage unavailable */ }
})();
