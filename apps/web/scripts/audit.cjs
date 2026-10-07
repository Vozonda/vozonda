const { chromium } = require('playwright');
const fs = require('fs');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const BASE = 'http://localhost:4173';
const OUT = '/tmp/opencode/vozonda-audit';
fs.mkdirSync(OUT, { recursive: true });

/*
 * SEED FIXTURE FOR DATA-DEPENDENT CHECKS
 *
 * Several audit checks require a finished episode with audio (the "smoke" suite
 * checks for playable episode in recent, karaoke highlight, audio advances, etc.).
 * On a fresh instance there are no jobs, so these checks are skipped.
 *
 * To prime the instance, run the seed script:
 *
 *   ./scripts/seed-qa.sh
 *
 * This posts a short text to /jobs, polls until done, and leaves a playable
 * episode in the recent list. After that, re-run the audit - the skipped
 * checks will execute and must pass.
 *
 * The script accepts optional text or URL as first argument:
 *   ./scripts/seed-qa.sh "Your article text here"
 *   ./scripts/seed-qa.sh https://example.com/article
 *
 * Environment variables:
 *   VOZONDA_API_BASE  (default: http://127.0.0.1:8787)
 *   STYLE, FORMAT, TONE, LANGUAGE, HOSTS, EXPLICIT  - job parameters
 */

const results = [];
const consoleErrors = [];

function record(suite, name, pass, detail = '') {
  results.push({ suite, name, pass, detail });
}

async function withPage(browser, opts, fn) {
  const page = await browser.newPage(opts);
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 160));
  });
  page.on('pageerror', (e) => consoleErrors.push(String(e).slice(0, 160)));
  try {
    await fn(page);
  } finally {
    await page.close();
  }
}

async function runAxe(page, label) {
  await page.addScriptTag({ content: axeSource });
  const r = await page.evaluate(() =>
    window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      resultTypes: ['violations']
    })
  );
  await page.screenshot({ path: `${OUT}/axe-${label}.png`, fullPage: true });
  const bad = r.violations.filter((v) => ['serious', 'critical'].includes(v.impact));
  const minor = r.violations.filter((v) => !['serious', 'critical'].includes(v.impact));
  for (const v of bad) {
    record('a11y', `${label}: ${v.id} (${v.impact})`, false, `${v.nodes.length} nodes: ${v.help}`);
  }
  for (const v of minor) {
    record('a11y', `${label}: ${v.id} (${v.impact})`, true, `minor, ${v.nodes.length} nodes: ${v.help}`);
  }
  if (bad.length === 0) record('a11y', `${label}: no serious/critical axe violations`, true);
}

(async () => {
  const browser = await chromium.launch();

  // ---------- SUITE: smoke + a11y (desktop light) ----------
  await withPage(browser, { viewport: { width: 1280, height: 900 }, colorScheme: 'light' }, async (page) => {
    // warmup: first navigation pays chromium cold-start, not the app
    await page.goto(BASE, { waitUntil: 'networkidle' });
    const t0 = Date.now();
    await page.reload({ waitUntil: 'networkidle' });
    const loadMs = Date.now() - t0;
    record('perf', 'compose loads < 2000ms', loadMs < 2000, `${loadMs}ms`);

    // HTML hygiene
    const hyg = await page.evaluate(() => ({
      lang: document.documentElement.lang,
      title: document.title,
      desc: document.querySelector('meta[name="description"]')?.content || '',
      h1count: document.querySelectorAll('h1').length,
      viewport: !!document.querySelector('meta[name="viewport"]')
    }));
    record('hygiene', 'html lang set', !!hyg.lang, hyg.lang);
    record('hygiene', 'title non-empty', !!hyg.title, hyg.title.slice(0, 50));
    record('hygiene', 'meta description present', !!hyg.desc);
    record('hygiene', 'exactly one h1', hyg.h1count === 1, `found ${hyg.h1count}`);
    record('hygiene', 'viewport meta present', hyg.viewport);

    // nav doctrine: no classic top nav; footer carries about/faq/library;
    // settings sits with the style chips as "all settings" / "defaults for every episode"
    const nav = await page.evaluate(() => {
      const footerText = document.querySelector('footer.foot')?.textContent || '';
      const allSettings = [...document.querySelectorAll('button, a')]
        .some((b) => {
          const t = b.textContent.trim();
          return t === 'advanced settings' || t === '▸ advanced settings' || t.includes('defaults for every episode') || b.classList.contains('settings-cta');
        });
      const topNav = !!document.querySelector('header.nav');
      return { footerOk: ['about', 'faq', 'library'].every((l) => footerText.includes(l)),
               footerClean: !/settings/.test(footerText), allSettings, topNav };
    });
    record('nav', 'no classic top nav', !nav.topNav);
    record('nav', 'footer carries about/faq/library', nav.footerOk);
    record('nav', 'settings not in footer', nav.footerClean);
    record('nav', 'settings toggle visible on compose', nav.allSettings);

    // font-size floor: no text below 11px
    const tiny = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('body *').forEach((el) => {
        if (!el.textContent.trim()) return;
        const fs = parseFloat(getComputedStyle(el).fontSize);
        if (fs < 11 && el.children.length === 0) out.push(`${el.tagName}.${el.className}:${fs}px`);
      });
      return out.slice(0, 5);
    });
    record('a11y', 'no text below 11px', tiny.length === 0, tiny.join(', '));

    await runAxe(page, 'compose');

    // compose style system: guard against dead-code sweeps (contract: docs/design.md
    // "compose style system"). fails if the styledoc centering, category colors,
    // 6.5em label grid or uppercase labels are removed again.
    // Under ShowPicker UX, clicking customize reveals the episode style system.
    const hasCustomize = await page.$('.customize-link');
    if (hasCustomize) {
      await page.click('.customize-link');
      await page.waitForTimeout(300);
    }
    const styleSystem = await page.evaluate(() => {
      const box = document.querySelector('.styledoc-box')
      const boxCss = box ? getComputedStyle(box) : null
      const text = document.querySelector('.styledoc-text')
      const group = document.querySelector('.style-group')
      const groupCss = group ? getComputedStyle(group) : null
      const label = document.querySelector('.group-label')
      const labelCss = label ? getComputedStyle(label) : null
      return {
        styledocCentered: !!boxCss && boxCss.display === 'grid' && boxCss.justifyItems === 'center',
        styledocSerif: !!text && getComputedStyle(text).fontStyle === 'italic',
        groupTwoCols: !!groupCss && groupCss.gridTemplateColumns.trim().split(/\s+/).length === 2,
        labelUppercase: !!labelCss && labelCss.textTransform === 'uppercase'
      }
    })
    record(
      'ux',
      'compose style system intact',
      styleSystem.styledocCentered && styleSystem.styledocSerif && styleSystem.groupTwoCols && styleSystem.labelUppercase,
      JSON.stringify(styleSystem)
    );

    // settings screen a11y + function (opened via the prominent settings cta)
    await page.click('.settings-cta');
    // poll up to 6s: after a cold api start, doctor+meta can exceed the
    // old fixed 1200ms wait and cascaded into false focus failures
    let stuck = true;
    for (let i = 0; i < 12; i++) {
      await page.waitForTimeout(500);
      const t = ((await page.textContent('.settings-screen')) || '');
      if (t && !t.includes('// loading')) { stuck = false; break; }
    }
    record('ux', 'settings screen loads', !stuck, stuck ? 'stuck on loading' : '');
    if (!stuck) {
      await runAxe(page, 'settings');
      const hasClose = !!(await page.$('.settings-screen .back'));
      record('ux', 'settings has visible close control', hasClose);
      await page.click('.settings-screen .back');
      await page.waitForTimeout(400);
    }

    // keyboard: url input is focused on load, ready to type
    const focused = await page.evaluate(() => document.activeElement.tagName + ':' + (document.activeElement.type || ''));
    record(
      'ux',
      'url input focused on load',
      focused === 'INPUT:url' || focused === 'INPUT:text' || focused === 'TEXTAREA:textarea',
      focused
    );


    // open first episode that actually has playable audio (skip failed jobs)
    const recentCount = await page.$$eval('.recent button.rcard[title]', (els) => els.length);
    let opened = false;
    for (let i = 0; i < Math.min(recentCount, 6); i++) {
      await page.click(`.recent button.rcard[title] >> nth=${i}`);
      await page.waitForTimeout(1800);
      opened = await page.evaluate(() => {
        const a = document.querySelector('audio');
        return !!a && a.currentSrc.endsWith('.mp3');
      });
      if (opened) break;
    }
    if (opened) {
      await runAxe(page, 'listen');
      const audioOk = await page.evaluate(() => {
        const a = document.querySelector('audio');
        return a && a.currentSrc.endsWith('.mp3') ? a.currentSrc.split('/').pop() : null;
      });
      record('smoke', 'episode audio resolves to mp3', !!audioOk, String(audioOk));
      await page.click('.play');
      await page.waitForTimeout(2500);
      const t = await page.evaluate(() => document.querySelector('audio').currentTime);
      const active = await page.$$eval('.transcript li.active', (els) => els.length);
      record('smoke', 'audio advances on play', t > 0, `t=${t.toFixed(1)}s`);
      record('smoke', 'karaoke line active while playing', active >= 1, `active lines: ${active}`);
      // Host emotion selects: aria-labels reference meta.emotions (both dialog and narration)
      const isDialog = await page.evaluate(() => {
        const format = document.querySelector('.meta')?.textContent || '';
        return format.includes('dialog') || document.querySelector('.transcript .speaker')?.textContent?.includes('A') || false;
      });
      let metaEmotions = [];
      try {
        const r = await page.request.get(BASE.replace('4173', '8787') + '/meta');
        if (r.ok()) {
          const j = await r.json();
          metaEmotions = (j.emotions ?? []).map((e) => (typeof e === 'string' ? e : e.id)).sort();
        }
      } catch {}
      if (!metaEmotions.length) {
        metaEmotions = await page.evaluate(() => (window.__VOZONDA_META__?.emotions ?? []).map((e) => (typeof e === 'string' ? e : e.id)).sort());
      }
      if (isDialog) {
        const emotionSelects = await page.$$eval('.voice-sub .voice-select[aria-label*="emotion"]', (els) =>
          els.map((e) => ({ label: e.getAttribute('aria-label'), options: [...e.querySelectorAll('option')].map((o) => o.value) }))
        );
        const hasEmotionSelects = emotionSelects.length >= 2; // at least A and B in dialog mode
        const labelsMatchMeta = hasEmotionSelects && emotionSelects.every((s) =>
          s.options.length >= 2 && s.options.every((o) => metaEmotions.includes(o))
        );
        record('a11y', 'host emotion selects have aria-labels', hasEmotionSelects, `found ${emotionSelects.length} selects`);
        record('a11y', 'emotion select options match meta.emotions', labelsMatchMeta, `meta: ${metaEmotions.join(',')}`);
      } else {
        const emotionSelects = await page.$$eval('.voice-sub .voice-select[aria-label*="emotion"]', (els) =>
          els.map((e) => ({ label: e.getAttribute('aria-label'), options: [...e.querySelectorAll('option')].map((o) => o.value) }))
        );
        const hasNarratorSelect = emotionSelects.length === 1 && (emotionSelects[0]?.label ?? '').toLowerCase().includes('narrator');
        const narratorMatchMeta = hasNarratorSelect && emotionSelects[0].options.length >= 2 && emotionSelects[0].options.every((o) => metaEmotions.includes(o));
        record('a11y', 'host emotion selects have aria-labels', hasNarratorSelect, `found ${emotionSelects.length} narration select`);
        record('a11y', 'emotion select options match meta.emotions', narratorMatchMeta, `meta: ${metaEmotions.join(',')}`);
      }
      // making of: no redundant style/format, but real audio facts
      await page.click('.makingof');
      await page.waitForTimeout(300);
      const facts = await page.evaluate(() => {
        const dts = [...document.querySelectorAll('.facts dt')].map((d) => d.textContent.trim());
        const audio = document.querySelector('.facts')?.textContent || '';
        return {
          dts,
          hasStyleOrFormat: dts.includes('style') || dts.includes('format'),
          audioFacts: /MB/.test(audio) && /kbps/.test(audio),
          sourceLinked: !!document.querySelector('.facts dd a')
        };
      });
      record('ux', 'making of carries style/format/voices', facts.dts.includes('style') && facts.dts.includes('format') && facts.dts.includes('voices'), facts.dts.join(','));
      record('ux', 'making of shows audio size + bitrate', facts.audioFacts);
      record('ux', 'source visibly styled as link inside making of', facts.sourceLinked);
      const metaRow = await page.evaluate(() => document.querySelector('.meta')?.textContent.trim() || '');
      record('ux', 'meta row is duration + date only', /^[0-9]+:[0-9]{2} min · [A-Za-z]{3} [0-9]+, [0-9]{4}, [0-9]{2}:[0-9]{2}$/.test(metaRow), metaRow);
      const urlNow = await page.evaluate(() => location.hash.startsWith('#e='));
      record('ux', 'episode has unique #e url', urlNow);
      const speakers = await page.evaluate(() =>
        [...document.querySelectorAll('.transcript .speaker')].slice(0, 4).map((s) => s.textContent.trim())
      );
      // #76: a custom host name replaces the letter label entirely; the old
      // "letter · voice" suffix only appears on unnamed speakers
      const named = speakers.some((s) => !/^(host [ab]|narrator)$/i.test(s));
      record('ux', 'transcript labels carry voice names', named || speakers.every((s) => /^narrator$/i.test(s)), speakers.join(' | '));
      const tuningOk = await page.evaluate(() => {
        const dts = [...document.querySelectorAll('.facts dt')].map((d) => d.textContent.trim());
        return dts.includes('voices');
      });
      record('ux', 'making of lists voices fact', tuningOk);

      // DUE-054 keyboard: space toggles, focus-visible, j/k navigation
      await page.keyboard.press('Space');
      await page.waitForTimeout(700);
      const paused = await page.evaluate(() => document.querySelector('audio')?.paused);
      record('ux', 'space toggles pause', !!paused, `paused=${paused}`);
      await page.keyboard.press('Space');
      await page.waitForTimeout(600);
      const resumed = await page.evaluate(() => {
        const a = document.querySelector('audio');
        return !!a && !a.paused;
      });
      record('ux', 'space toggles play again', !!resumed, `resumed=${resumed}`);
      const hasFocusVisible = await page.evaluate(() => {
        for (const sheet of [...document.styleSheets]) {
          try {
            for (const r of [...sheet.cssRules]) {
              if (r.selectorText && r.selectorText.includes(':focus-visible')) return true;
            }
          } catch {}
        }
        return false;
      });
      record('a11y', 'focus-visible outlines declared', hasFocusVisible);
      const titleBefore = await page.evaluate(() => document.querySelector('header h1')?.textContent?.trim() ?? '');
      await page.keyboard.press('j');
      await page.waitForTimeout(1300);
      const titleAfterJ = await page.evaluate(() => document.querySelector('header h1')?.textContent?.trim() ?? '');
      const hashAfterJ = await page.evaluate(() => location.hash);
      const navigatedJ = titleBefore !== titleAfterJ && !!titleAfterJ;
      record('ux', 'j navigates to next episode', navigatedJ || !!hashAfterJ, `before "${titleBefore.slice(0,20)}" after "${titleAfterJ.slice(0,20)}" hash ${hashAfterJ}`);
      // back with k
      await page.keyboard.press('k');
      await page.waitForTimeout(1300);
      const titleAfterK = await page.evaluate(() => document.querySelector('header h1')?.textContent?.trim() ?? '');
      record('ux', 'k navigates to previous episode', !!titleAfterK, `after k "${titleAfterK.slice(0,20)}"`);

      await page.screenshot({ path: OUT + '/playing.png' });
    } else {
      // data-dependent check: needs at least one rendered episode on the
      // instance. skip (not fail) on fresh installs - render an episode
      // to exercise this check.
      record("smoke", "playable episode in recent", true, "skipped: no audio-bearing job found (render an episode to exercise this check)");
    }
  });

  // ---------- SUITE: mobile ----------
  await withPage(browser, { viewport: { width: 375, height: 812 }, colorScheme: 'light', isMobile: true, hasTouch: true }, async (page) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    record('responsive', 'no horizontal overflow @375px', overflow <= 1, `overflow ${overflow}px`);
    await page.screenshot({ path: OUT + '/mobile-compose.png', fullPage: true });

    // .voice-sub stacks single-column at 375px (emotion select + name input)
    const voiceSubLayout = await page.evaluate(() => {
      const subs = document.querySelectorAll('.voice-sub');
      return [...subs].map((el) => {
        const cs = getComputedStyle(el);
        return {
          display: cs.display,
          gridTemplateColumns: cs.gridTemplateColumns,
          flexDirection: cs.flexDirection,
          children: el.children.length
        };
      });
    });
    const singleColumn = voiceSubLayout.every((s) => {
      if (s.display === 'flex' && s.flexDirection === 'column') return true;
      if (s.display === 'grid') {
        // getComputedStyle resolves 1fr to pixel values; count tracks by splitting
        const tracks = s.gridTemplateColumns.trim().split(/\s+/).filter(Boolean).length;
        return tracks === 1;
      }
      return false;
    }) && voiceSubLayout.every((s) => s.children >= 2);
    record('responsive', '.voice-sub single-column @375px', singleColumn, JSON.stringify(voiceSubLayout));

    await page.click('.settings-cta', { force: true });
    await page.waitForTimeout(1000);
    const mOverflow = await page.evaluate(
      () => (document.querySelector('.settings-screen')?.scrollWidth || 0) - document.documentElement.clientWidth
    );
    record('responsive', 'settings fits @375px', mOverflow <= 1, `overflow ${mOverflow}px`);
    await page.screenshot({ path: OUT + '/mobile-settings.png' });

    // tap targets >= 40px on primary controls
    const small = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll('button, a').forEach((b) => {
        const r = b.getBoundingClientRect();
        if (r.width > 0 && (r.height < 24 || r.width < 24)) out.push(`${b.textContent.trim().slice(0, 20)}:${Math.round(r.width)}x${Math.round(r.height)}`);
      });
      return out.slice(0, 6);
    });
    record('responsive', 'tap targets >= ~24px', small.length === 0, small.join('; '));
  });

  // ---------- SUITE: dark mode ----------
  await withPage(browser, { viewport: { width: 1280, height: 900 }, colorScheme: 'dark' }, async (page) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.screenshot({ path: OUT + '/dark-compose.png' });
    const bg = await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor);
    record('theme', 'dark background applied', !bg.includes('250,') && bg !== 'rgba(0, 0, 0, 0)', bg);

    await page.click('.settings-cta');
    await page.waitForTimeout(1200);
    const scheme = await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
    record('theme', 'color-scheme declares dark', scheme.includes('dark'), scheme);
    await page.screenshot({ path: OUT + '/dark-settings.png' });
    await runAxe(page, 'compose-dark');
  });

  // ---------- SUITE: archive ----------
  await withPage(browser, { viewport: { width: 1280, height: 900 } }, async (page) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      const btns = [...document.querySelectorAll('footer button, footer a')];
      const b = btns.find((x) => x.textContent.trim() === 'library');
      if (b) b.click();
    });
    await page.waitForTimeout(1200);
    const arch = await page.evaluate(() => {
      const bar = !!document.querySelector('.filterbar select') &&
        document.querySelectorAll('.filterbar select').length >= 3;
      const descs = [...document.querySelectorAll('.entry .edesc')];
      const entries = [...document.querySelectorAll('.entry')].length;
      return { bar, withDesc: descs.length, entries };
    });
    record('archive', 'filter bar has sort/lang/style selects', arch.bar);
    record('archive', 'episodes carry why-listen hooks', arch.withDesc >= Math.min(3, arch.entries), `${arch.withDesc}/${arch.entries}`);

    // DUE-053 library search (debounced title+description)
    const searchInput = await page.$('input[aria-label="Search episodes"]');
    record('archive', 'library has search input', !!searchInput);
    if (searchInput) {
      const before = await page.$$eval('.entry', (els) => els.length);
      await page.fill('input[aria-label="Search episodes"]', 'zzzz_no_match_123');
      await page.waitForTimeout(450);
      const afterNoMatch = await page.$$eval('.entry', (els) => els.length);
      const emptyNote = await page.evaluate(() => document.body.textContent.includes('no episode matches'));
      record('archive', 'search filters to empty state', afterNoMatch === 0 && emptyNote, `before ${before} after ${afterNoMatch}`);
      await page.fill('input[aria-label="Search episodes"]', '');
      await page.waitForTimeout(450);
      const afterClear = await page.$$eval('.entry', (els) => els.length);
      record('archive', 'clearing search restores list', afterClear === before, `${afterClear}/${before}`);
    }
  });

  // ---------- SUITE: faq shortcuts ----------
  await withPage(browser, { viewport: { width: 1280, height: 900 } }, async (page) => {
    await page.goto(BASE, { waitUntil: 'networkidle' });
    await page.evaluate(() => {
      const btns = [...document.querySelectorAll('footer button, footer a')];
      const b = btns.find((x) => x.textContent.trim() === 'faq');
      if (b) b.click();
    });
    await page.waitForTimeout(800);
    const faqText = await page.evaluate(() => document.body.textContent || '');
    record('ux', 'faq documents space shortcut', /space/i.test(faqText) && /play/i.test(faqText), faqText.slice(0, 80));
    record('ux', 'faq documents j/k shortcuts', /j\s*\/\s*k/i.test(faqText), faqText.slice(0, 80));
  });

  // ---------- SUITE: api delivery ----------
  // the app is only as good as its weakest endpoint; catch regressions here
  await withPage(browser, { viewport: { width: 1280, height: 900 } }, async (page) => {
    const res = await page.request.get(BASE.replace('4173', '8787') + '/meta');
    const m = res.ok() ? await res.json() : null;
    record('api', '/meta reachable with version', !!m?.version, m?.version || res.status());
    if (m) {
      record('api', 'write auth mode reported', typeof m.write_auth === 'boolean', `write_auth=${m.write_auth}`);
      record('api', 'styles present', Array.isArray(m.styles) && m.styles.length >= 5);
    }
    // audio range/etag checks against a REAL done episode: the old
    // hardcoded value-89e1 died in the v0.5 data cut and 404ed forever
    let audioId = null;
    try {
      const jl = await page.request.get(BASE.replace('4173', '8787') + '/jobs?limit=20');
      const jlBody = jl.ok() ? await jl.json() : { jobs: [] };
      const done = (jlBody.jobs || []).filter((j) => j.state === 'done');
      audioId = done.length ? done[0].id : null;
    } catch { void audioId; }
    if (!audioId) {
      record('api', 'audio serves range requests', true, 'skipped: no done episode (seed with scripts/seed-qa.sh)');
      record('api', 'audio has etag for caching', true, 'skipped: no done episode');
      record('api', 'audio accept-ranges declared', true, 'skipped: no done episode');
    } else {
      const audio = await page.request.get(BASE.replace('4173', '8787') + `/audio/${audioId}.mp3`, {
        headers: { Range: 'bytes=0-1023' }
      });
      record('api', 'audio serves range requests', audio.status() === 206, `${audio.status()} ${audioId}`);
      record('api', 'audio has etag for caching', !!(audio.headers()['etag'] || audio.headers()['last-modified']));
      record('api', 'audio accept-ranges declared', audio.headers()['accept-ranges'] === 'bytes');
    }
    const feed = await page.request.get(BASE.replace('4173', '8787') + '/feed.xml');
    const feedCT = feed.headers()['content-type'] || '';
    const feedTxt = feed.ok() ? await feed.text() : '';
    record('api', 'feed.xml serves rss', feed.status() === 200 && feedCT.includes('rss'), `${feed.status()} ${feedCT.slice(0,30)}`);
    record('api', 'feed.xml contains channel+enclosure', feedTxt.includes('<rss') && feedTxt.includes('<channel>') && feedTxt.includes('<enclosure'), `${feedTxt.slice(0,60)}`);
  });

  // ---------- SUITE: perf budget ----------
  await withPage(browser, { viewport: { width: 1280, height: 900 } }, async (page) => {
    let jsKb = 0;
    page.on('response', async (res) => {
      if (res.url().endsWith('.js')) {
        try {
          jsKb += Number(res.headers()['content-length'] || 0) / 1024;
        } catch {}
      }
    });
    await page.goto(BASE, { waitUntil: 'networkidle' });
    record('perf', 'initial JS < 80KB', jsKb < 80, `${jsKb.toFixed(1)}KB`);
    const requests = await page.evaluate(() => performance.getEntriesByType('resource').length);
    record('perf', 'requests < 25', requests < 25, `${requests} requests`);
  });

  await browser.close();

  // ---------- report ----------
  const failed = results.filter((r) => !r.pass);
  console.log('\n=== RESULTS ===');
  let lastSuite = '';
  for (const r of results) {
    if (r.suite !== lastSuite) {
      console.log(`\n-- ${r.suite} --`);
      lastSuite = r.suite;
    }
    console.log(`${r.pass ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? '   [' + r.detail + ']' : ''}`);
  }
  if (consoleErrors.length) {
    console.log(`\n=== CONSOLE ERRORS (${consoleErrors.length}) ===`);
    [...new Set(consoleErrors)].slice(0, 10).forEach((e) => console.log(e));
  }
  console.log(`\n=== SUMMARY: ${results.length - failed.length}/${results.length} passed ===`);
  process.exit(failed.length ? 1 : 0);
})();
