import { chromium } from 'playwright';

const BASE = 'http://localhost:4173';
const API = 'http://localhost:8787';

async function test() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const issues = [];

  console.log('=== TEST JOURNEY ROUND 2: v0.5.0 surfaces ===\n');

  // 1. Watchlist: add a feed, toggle digest, render digest now
  console.log('1. WATCHLIST DIGEST FLOW');
  await page.goto(`${BASE}/#watchlist`);
  await page.waitForTimeout(500);

  const addUrl = await page.$('input[placeholder*="feed"], input[placeholder*="rss"], input[type="url"]');
  if (addUrl) {
    await addUrl.fill('https://feeds.bbci.co.uk/news/rss.xml');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(2000);
    console.log('  ✓ Feed added');
  } else {
    issues.push('Watchlist: No feed URL input found');
  }

  await page.waitForTimeout(500);
  const digestToggle = await page.$('input[type="radio"][value="digest"], .feed-card input[type="checkbox"]');
  if (digestToggle) {
    console.log('  ✓ Digest toggle found');
    await digestToggle.click();
    await page.waitForTimeout(500);
  } else {
    issues.push('Watchlist: Digest toggle not found on feed card');
  }

  const renderBtn = await page.$('button:has-text("render"), button:has-text("digest"), button:has-text("now")');
  if (renderBtn) {
    console.log('  ✓ Render digest now button found');
  } else {
    issues.push('Watchlist: "Render digest now" button not found');
  }

  const countSelect = await page.$('select[name*="count"], select[id*="count"], .feed-card select');
  if (countSelect) {
    console.log('  ✓ Digest count select found');
  } else {
    issues.push('Watchlist: Digest count select not found');
  }

  // 2. ENGINE SWITCH (PUT /tts/engine)
  console.log('\n2. ENGINE SWITCH');
  await page.goto(`${BASE}/#settings`);
  await page.waitForTimeout(1000);

  const engineSelect = await page.$('select[name*="engine"], select[id*="engine"], .settings-screen select');
  if (engineSelect) {
    const options = await engineSelect.$$('option');
    console.log(`  ✓ Engine select found with ${options.length} options`);
    for (const opt of options) {
      const val = await opt.getAttribute('value');
      const text = await opt.textContent();
      console.log(`    - ${val}: ${text}`);
    }
  } else {
    issues.push('Settings: Engine select not found');
  }

  // 3. WATCHLIST SETTINGS EDITOR (style/format editable per card)
  console.log('\n3. WATCHLIST SETTINGS EDITOR');
  await page.goto(`${BASE}/#watchlist`);
  await page.waitForTimeout(500);

  const feedCard = await page.$('.feed-card, .watchlist-card, [class*="feed"]');
  if (feedCard) {
    const settingsBtn = await feedCard.$('button:has-text("settings"), button:has-text("edit"), .feed-settings summary, details.feed-settings summary');
    if (settingsBtn) {
      console.log('  ✓ Feed settings expander found');
      await settingsBtn.click();
      await page.waitForTimeout(500);

      const styleSelect = await feedCard.$('select[name*="style"], select[id*="style"]');
      const formatSelect = await feedCard.$('select[name*="format"], select[id*="format"]');
      const langSelect = await feedCard.$('select[name*="language"], select[id*="language"]');
      const hostsSelect = await feedCard.$('select[name*="hosts"], select[id*="hosts"]');
      const explicitCheck = await feedCard.$('input[type="checkbox"][name*="explicit"]');

      if (styleSelect) console.log('  ✓ Style select in feed settings');
      else issues.push('Watchlist settings: Style select missing');

      if (formatSelect) console.log('  ✓ Format select in feed settings');
      else issues.push('Watchlist settings: Format select missing');

      if (langSelect) console.log('  ✓ Language select in feed settings');
      else issues.push('Watchlist settings: Language select missing');

      if (hostsSelect) console.log('  ✓ Hosts select in feed settings');
      else issues.push('Watchlist settings: Hosts select missing');

      if (explicitCheck) console.log('  ✓ Explicit checkbox in feed settings');
      else issues.push('Watchlist settings: Explicit checkbox missing');
    } else {
      issues.push('Watchlist: Feed settings expander (details.feed-settings) not found');
    }
  } else {
    issues.push('Watchlist: No feed cards found');
  }

  // 4. WATCH-A-FEED REWORK (tune expander, url normalization)
  console.log('\n4. WATCH-A-FEED REWORK (compose screen tune expander)');
  await page.goto(`${BASE}/`);
  await page.waitForTimeout(500);

  const tuneExpander = await page.$('details:has(summary:has-text("tune")), details:has(summary:has-text("optional")), details:has(summary:has-text("before adding"))');
  if (tuneExpander) {
    console.log('  ✓ Tune expander found on compose');
    const isOpen = await tuneExpander.evaluate(el => el.open);
    console.log(`  - Initially open: ${isOpen}`);

    const helpLine = await tuneExpander.$('p:has-text("paste any rss"), p:has-text("tune style")');
    if (helpLine) {
      const text = await helpLine.textContent();
      console.log(`  ✓ Help line: "${text.trim()}"`);
    } else {
      issues.push('Compose: Tune expander help line missing');
    }

    if (!isOpen) {
      await tuneExpander.evaluate(el => el.open = true);
      await page.waitForTimeout(300);
    }

    const styleSelect = await tuneExpander.$('select[name*="style"], select[id*="style"]');
    const formatSelect = await tuneExpander.$('select[name*="format"], select[id*="format"]');
    const voiceSelect = await tuneExpander.$('select[name*="voice"], select[id*="voice"]');

    if (styleSelect) console.log('  ✓ Style select in tune expander');
    else issues.push('Compose tune expander: Style select missing');

    if (formatSelect) console.log('  ✓ Format select in tune expander');
    else issues.push('Compose tune expander: Format select missing');
  } else {
    issues.push('Compose: Tune expander not found');
  }

  // 5. LISTEN VIEW - chapters
  console.log('\n5. LISTEN VIEW - CHAPTERS');
  await page.goto(`${BASE}/e/pasted-15fd`);
  await page.waitForTimeout(2000);

  const chapters = await page.$('ol.chapters, .chapters ol, nav[aria-label*="chapter"] ol');
  if (chapters) {
    console.log('  ✓ Chapters list found on listen view');
    const chapterBtns = await chapters.$$('button, a');
    console.log(`  - ${chapterBtns.length} chapter buttons`);
  } else {
    issues.push('Listen: Chapters list not found on /e/{id}');
  }

  const disclosure = await page.$('details:has(summary:has-text("made")), details:has(summary:has-text("How it"))');
  if (disclosure) {
    console.log('  ✓ "How it was made" disclosure found');
  } else {
    issues.push('Listen: "How it was made" disclosure missing');
  }

  // 6. LIBRARY - digest badge
  console.log('\n6. LIBRARY - DIGEST BADGE');
  await page.goto(`${BASE}/#library`);
  await page.waitForTimeout(500);

  const digestBadge = await page.$('.digest-badge, [class*="digest"], .library-item:has-text("digest")');
  if (digestBadge) {
    console.log('  ✓ Digest badge found in library');
  } else {
    issues.push('Library: Digest badge not found');
  }

  await browser.close();

  console.log('\n=== SUMMARY ===');
  if (issues.length === 0) {
    console.log('ALL CHECKS PASSED - no issues found');
  } else {
    console.log(`${issues.length} issues found:`);
    issues.forEach((issue, i) => console.log(`  ${i+1}. ${issue}`));
  }
  return issues;
}

test().catch(console.error);
