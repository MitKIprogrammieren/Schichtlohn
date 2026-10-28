// SchichtLohn – Lader für die Home-Assistant-Karte (custom:schichtlohn-card).
// Holt immer den neuesten Stand aus dem GitHub-Repo über jsDelivr (auf den Commit festgelegt,
// weil jsDelivr unter @main bis zu 12 Stunden alte Dateien liefert). Commit wird 10 Minuten gemerkt.
(async () => {
  const R = "MitKIprogrammieren/Schichtlohn", K = "sl_karte_commit", ok = s => /^[0-9a-f]{40}$/.test(s || "");
  let alt = null; try { alt = JSON.parse(localStorage.getItem(K) || "null"); } catch (e) {}
  let sha = alt && Date.now() - alt.t < 6e5 ? alt.s : "";
  if (!ok(sha)) {
    try {
      const r = await fetch(`https://api.github.com/repos/${R}/commits/main`, { headers: { Accept: "application/vnd.github.sha" } });
      if (r.ok) { sha = (await r.text()).trim(); if (ok(sha)) try { localStorage.setItem(K, JSON.stringify({ s: sha, t: Date.now() })); } catch (e) {} }
    } catch (e) {}
  }
  if (!ok(sha)) sha = alt && ok(alt.s) ? alt.s : "main";
  await import(`https://cdn.jsdelivr.net/gh/${R}@${sha}/homeassistant/schichtlohn-card.js`);
})();
