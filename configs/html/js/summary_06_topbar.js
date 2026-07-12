/* summary_06_topbar.js — kcommit-analysis-pipeline
 *
 * Topbar meta pills: version, run timestamp, git range, kernel version.
 */

(function () {
  const bar = document.getElementById('kc-topbar-pills');
  if (!bar) return;
  const pills = [];

  function localTzLabel() {
    try {
      const parts = new Intl.DateTimeFormat(undefined, {
        hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
      }).formatToParts(new Date());
      const tz = parts.find(p => p.type === 'timeZoneName');
      return tz ? tz.value : '';
    } catch (_) { return ''; }
  }

  if (META.version) pills.push(esc(META.version));
  if (META.generated_at) {
    const ts = String(META.generated_at).slice(0, 16), tz = localTzLabel();
    pills.push(`Run: ${esc(ts)}${tz ? ` ${esc(tz)}` : ''}`);
  }
  if (META.git_range) {
    const parts = String(META.git_range).split('..');
    if (parts.length === 2)
      pills.push(`From ${esc(parts[0].trim())} to ${esc(parts[1].trim())}`);
    else
      pills.push(`Range: ${esc(META.git_range)}`);
  }
  if (META.kernel_ver) pills.push(`Kernel: ${esc(META.kernel_ver)}`);

  bar.innerHTML = pills.map(p => `<span class="kc-meta-pill">${p}</span>`).join('');
})();
