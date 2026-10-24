// ==UserScript==
// @name         Inbox Only
// @description  Instagram as a plain messenger: DMs stay, feeds, reels, stories and videos are gone.
// @version      1.0.0
// @match        https://www.instagram.com/*
// @match        https://instagram.com/*
// @run-at       document-start
// @inject-into  content
// @noframes
// @grant        none
// ==/UserScript==

// One file, three hosts: the Safari Web Extension (manifest.json), the iOS
// app's WKWebView (injected at document start), and the Userscripts app.
// It only touches the DOM, so it needs no extension APIs.

(() => {
  'use strict';
  if (window.__inboxOnly) return;
  window.__inboxOnly = true;

  const HOME = '/direct/inbox/';

  // Messaging, plus every page Instagram's login / 2FA / checkpoint flow uses.
  const ALLOWED = /^\/(direct|accounts|challenge|two_factor|auth_platform|consent|legal|privacy|oauth|emails?|session|api)(\/|$)/;
  const isAllowed = (path) => ALLOWED.test(path);

  // ---------------------------------------------------------------- styles

  const CSS = `
    html { -webkit-text-size-adjust: 100%; }
    html, body { overscroll-behavior: none; -webkit-tap-highlight-color: transparent; }

    /* Doors back into the feed: home, explore, reels, create, app-store nags. */
    a[href="/"], a[href="/explore/"], a[href^="/explore/"], a[href^="/reels"],
    a[href^="/create"], a[href*="apps.apple.com"], a[href*="itunes.apple.com"] {
      display: none !important;
    }

    /* Every video is invisible until proven to be a voice message. */
    video:not([data-io-audio]) { opacity: 0 !important; pointer-events: none !important; }

    :has(> video[data-io-blocked]) { position: relative !important; }
    :has(> video[data-io-blocked])::after,
    [data-io-reel]::after {
      content: attr(data-io-label);
      position: absolute; inset: 0; z-index: 2;
      display: flex; align-items: center; justify-content: center;
      font: 600 13px/1.2 -apple-system, system-ui, sans-serif;
      letter-spacing: .01em; color: rgba(255,255,255,.85);
      background: #2b2d31; border-radius: inherit; pointer-events: none;
    }
    :has(> video[data-io-blocked])::after { content: "Video blocked"; }
    [data-io-reel] { position: relative !important; }
    [data-io-reel] img, [data-io-reel] video { visibility: hidden !important; }

    #io-toast {
      position: fixed; left: 50%; bottom: calc(24px + env(safe-area-inset-bottom));
      transform: translate(-50%, 12px); opacity: 0; z-index: 2147483647;
      padding: 10px 16px; border-radius: 999px;
      font: 500 14px/1.2 -apple-system, system-ui, sans-serif;
      color: #fff; background: rgba(28,28,30,.92);
      -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);
      transition: opacity .18s ease, transform .18s ease; pointer-events: none;
    }
    #io-toast[data-on] { opacity: 1; transform: translate(-50%, 0); }
  `;

  function addStyle() {
    const style = document.createElement('style');
    style.id = 'io-style';
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  // ---------------------------------------------------------------- toast

  let toastTimer;
  function toast(text) {
    let el = document.getElementById('io-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'io-toast';
      document.documentElement.appendChild(el);
    }
    el.textContent = text;
    el.setAttribute('data-on', '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.removeAttribute('data-on'), 1600);
  }

  // ---------------------------------------------------------------- routes

  // Instagram is a single-page app, so a feed can open without a page load.
  // Poll the URL (content scripts can't hook the page's history API) and
  // bounce anything that isn't messaging.
  let lastGood = isAllowed(location.pathname) ? location.href : null;
  let leaving = 0;

  function guard() {
    if (isAllowed(location.pathname)) {
      lastGood = location.href;
      clearTimeout(leaving);
      leaving = 0;
      return;
    }
    if (leaving) return;
    // Only step back into a chat; after login Instagram lands on the feed,
    // and going back there would return to the login page.
    if (!lastGood || !new URL(lastGood).pathname.startsWith('/direct/')) {
      return location.replace(HOME);
    }
    // Came from a chat: step back so the chat keeps its scroll and state.
    history.back();
    leaving = setTimeout(() => {
      leaving = 0;
      if (!isAllowed(location.pathname)) location.replace(HOME);
    }, 700);
  }

  guard();
  setInterval(guard, 250);
  addEventListener('popstate', guard);

  // Taps on links to feeds, profiles, reels or stories never navigate.
  addEventListener('click', (e) => {
    const target = e.target instanceof Element ? e.target : null;
    if (!target) return;

    if (target.closest('[data-io-reel]')) return stop(e, 'Reels are blocked');

    const a = target.closest('a[href]');
    if (!a) return;
    let url;
    try { url = new URL(a.href, location.href); } catch { return; }
    const internal = url.origin === location.origin || /(^|\.)instagram\.com$/.test(url.hostname);
    if (internal && !isAllowed(url.pathname)) stop(e, 'Only messages here');
  }, true);

  function stop(e, message) {
    e.preventDefault();
    e.stopImmediatePropagation();
    toast(message);
  }

  // ---------------------------------------------------------------- videos

  // Voice messages may ride on a <video> element, so a video is only blocked
  // once its metadata shows an actual picture. Audio-only media keeps working.
  const hasPicture = (v) => v.videoWidth > 0 || v.videoHeight > 0;

  function block(v) {
    v.setAttribute('data-io-blocked', '');
    v.removeAttribute('data-io-audio');
    v.pause();
    v.autoplay = false;
    if (v.srcObject) v.srcObject = null;
    if (v.getAttribute('src') || v.currentSrc) {
      v.removeAttribute('src');
      v.load();
    }
  }

  function allowAsAudio(v) {
    v.setAttribute('data-io-audio', '');
    if (v.__ioWanted) {
      v.__ioWanted = false;
      v.play().catch(() => {});
    }
  }

  function onMedia(e) {
    const v = e.target;
    if (!(v instanceof HTMLVideoElement)) return;

    if (e.type === 'loadedmetadata') {
      hasPicture(v) ? block(v) : allowAsAudio(v);
      return;
    }
    // play / playing
    if (v.hasAttribute('data-io-audio')) return;
    if (v.readyState >= 1) {
      hasPicture(v) ? block(v) : allowAsAudio(v);
    } else {
      // Not known yet: hold it, and resume if it turns out to be audio.
      v.__ioWanted = true;
      v.pause();
      if (v.preload === 'none') v.preload = 'metadata';
    }
  }

  // Media events don't bubble, but capture-phase listeners still see them.
  for (const type of ['loadedmetadata', 'play', 'playing']) {
    addEventListener(type, onMedia, true);
  }

  // ---------------------------------------------------------------- shared reels

  // Story links aren't here: inbox avatars link to stories, and covering
  // avatars would hurt. The click guard still stops them from opening.
  const REEL_LINK = 'a[href*="/reel/"], a[href*="/reels/"], a[href*="/tv/"]';
  const REEL_ICON = /^(clip|clips|reel|reels|video)$/i;

  function scan() {
    for (const v of document.querySelectorAll('video:not([data-io-seen])')) {
      v.setAttribute('data-io-seen', '');
      v.autoplay = false;
      if (v.readyState >= 1) hasPicture(v) ? block(v) : allowAsAudio(v);
    }

    for (const a of document.querySelectorAll(`${REEL_LINK}:not([data-io-reel])`)) {
      markReel(a);
    }

    for (const svg of document.querySelectorAll('svg[aria-label]:not([data-io-seen])')) {
      svg.setAttribute('data-io-seen', '');
      if (!REEL_ICON.test(svg.getAttribute('aria-label').trim())) continue;
      const card = svg.closest('a, [role="button"], [role="link"]');
      // Skip the nav bar icon; only cards with a thumbnail are shared reels.
      if (card && card.querySelector('img')) markReel(card);
    }
  }

  function markReel(el) {
    el.setAttribute('data-io-reel', '');
    el.setAttribute('data-io-label', 'Reel hidden');
  }

  let scanQueued = false;
  const observer = new MutationObserver(() => {
    if (scanQueued) return;
    scanQueued = true;
    setTimeout(() => { scanQueued = false; scan(); }, 120);
  });

  // ---------------------------------------------------------------- app feel

  function tuneViewport() {
    // maximum-scale=1 stops iOS zooming into the message box on focus;
    // pinch-zoom still works in Safari.
    let meta = document.querySelector('meta[name="viewport"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'viewport';
      document.head.appendChild(meta);
    }
    meta.content = 'width=device-width, initial-scale=1, maximum-scale=1';

    // Tint Safari's bars to match the page (light or dark).
    const bg = getComputedStyle(document.body).backgroundColor;
    if (bg && bg !== 'rgba(0, 0, 0, 0)') {
      let theme = document.querySelector('meta[name="theme-color"]');
      if (!theme) {
        theme = document.createElement('meta');
        theme.name = 'theme-color';
        document.head.appendChild(theme);
      }
      theme.content = bg;
    }
  }

  // ---------------------------------------------------------------- start

  addStyle();
  observer.observe(document.documentElement, { childList: true, subtree: true });

  const ready = () => {
    // Instagram's renderer can replace <head>; make sure the styles survive.
    if (!document.getElementById('io-style')) addStyle();
    tuneViewport();
    scan();
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ready, { once: true });
  } else {
    ready();
  }
  addEventListener('load', ready, { once: true });
})();
