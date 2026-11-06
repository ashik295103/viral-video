// maint.js — রক্ষণাবেক্ষণ মোড + নিরাপদ লিংক হেল্পার
// index.html ও post.html এ config.js এর ঠিক পরে লোড হবে।

// ---- থিম (neon / sunset / ocean / light) ----
// পেজ খোলার সাথে সাথে আগের সেভ করা থিম বসায় (যাতে রঙ ঝলকে না যায়)।
// ?theme=light লিখে লিংক খুললে সেই থিম প্রিভিউ করা যায়।
var THEMES_OK = ['neon', 'sunset', 'ocean', 'light'];
(function () {
  var t = 'neon';
  try {
    var q = new URLSearchParams(location.search).get('theme');
    var s = localStorage.getItem('vvt');
    t = THEMES_OK.indexOf(q) >= 0 ? q : (THEMES_OK.indexOf(s) >= 0 ? s : 'neon');
  } catch (e) {}
  document.documentElement.setAttribute('data-theme', t);
})();
window.applyTheme = function (S) {
  try {
    var q = new URLSearchParams(location.search).get('theme');
    var t = THEMES_OK.indexOf(q) >= 0 ? q : (S && THEMES_OK.indexOf(S.theme) >= 0 ? S.theme : 'neon');
    document.documentElement.setAttribute('data-theme', t);
    if (THEMES_OK.indexOf(q) < 0) localStorage.setItem('vvt', t);
  } catch (e) {}
};

// শুধু http/https লিংক গ্রহণ করে (javascript: ইত্যাদি আটকায়)
window.safeUrl = function (u) {
  u = String(u == null ? '' : u).trim();
  return /^https?:\/\//i.test(u) ? u : '#';
};

// ---- Cloudflare Turnstile ক্যাপচা (config.js এ T: 'site-key' দিলে তবেই চালু হয়) ----
var CT;
window.capToken = function () { return CT; };
window.capReset = function () {
  CT = undefined;
  try { if (window.turnstile && window._cw !== undefined) window.turnstile.reset(window._cw); } catch (e) {}
};
window.capInit = function (id) {
  if (!window.CFG || !window.CFG.T) return;
  var el = document.getElementById(id);
  if (!el) return;
  var s = document.createElement('script');
  s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
  s.async = true;
  s.onload = function () {
    window._cw = window.turnstile.render(el, {
      sitekey: window.CFG.T,
      theme: 'dark',
      callback: function (t) { CT = t; },
      'expired-callback': function () { CT = undefined; }
    });
  };
  document.head.appendChild(s);
};

// true ফেরত দিলে পেজ আর লোড করা উচিত না
window.maintGate = function (S, prof) {
  var old = document.getElementById('mt-ov');
  if (old) old.remove();
  var oldb = document.getElementById('mt-bar');
  if (oldb) oldb.remove();

  if (!S || S.maintenance !== true) return false;

  // অ্যাডমিন লগইন থাকলে সাইট স্বাভাবিক দেখাবে, শুধু উপরে একটি সতর্কবার
  if (prof && prof.is_admin) {
    var bar = document.createElement('div');
    bar.id = 'mt-bar';
    bar.textContent = '🛠️ রক্ষণাবেক্ষণ মোড চালু আছে — সাধারণ ভিজিটররা সাইট দেখতে পাচ্ছে না (শুধু আপনি পাচ্ছেন)';
    bar.style.cssText = 'position:sticky;top:0;z-index:99998;background:#d68910;color:#fff;text-align:center;padding:6px 10px;font:13px system-ui,sans-serif';
    document.body.insertBefore(bar, document.body.firstChild);
    return false;
  }

  var msg = (S.maintenance_msg || '').trim() ||
    'ওয়েবসাইটে রক্ষণাবেক্ষণের কাজ চলছে। খুব দ্রুত সমাধান করা হবে। সাময়িক সময়ের জন্য আমরা দুঃখিত।';

  var ov = document.createElement('div');
  ov.id = 'mt-ov';
  ov.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:#0a0a14;color:#eee;display:flex;align-items:center;justify-content:center;padding:20px;text-align:center;font-family:system-ui,sans-serif;overflow:auto';

  var box = document.createElement('div');
  box.style.cssText = 'max-width:440px;width:100%;background:#18182b;border:1px solid #b44cff;border-radius:18px;padding:28px 22px';

  var ic = document.createElement('div');
  ic.textContent = '🛠️';
  ic.style.cssText = 'font-size:52px;margin-bottom:6px';
  box.appendChild(ic);

  var h = document.createElement('h2');
  h.textContent = 'রক্ষণাবেক্ষণের কাজ চলছে';
  h.style.cssText = 'margin:6px 0 14px;font-size:20px;color:#00e5ff';
  box.appendChild(h);

  // textContent ব্যবহার, তাই বার্তায় HTML থাকলেও চলবে না (XSS নিরাপদ)
  msg.split(/\n+/).forEach(function (line) {
    line = line.trim();
    if (!line) return;
    var p = document.createElement('p');
    p.textContent = line;
    p.style.cssText = 'line-height:1.8;margin:0 0 10px;color:#ddd;font-size:15px';
    box.appendChild(p);
  });

  var f = document.createElement('p');
  f.textContent = '— Viral Video টিম';
  f.style.cssText = 'margin:16px 0 0;color:#889;font-size:13px';
  box.appendChild(f);

  ov.appendChild(box);
  document.body.appendChild(ov);
  document.body.style.overflow = 'hidden';
  return true;
};
