// Test Source Tray browser round trips with Playwright
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const PORT = 4174;
const BASE = `http://localhost:${PORT}`;

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  console.log('--- Starting Source Tray Browser Round Trips ---');

  // 1. Start preview server on PORT 4174
  const webDir = path.resolve(__dirname, '..');
  const preview = spawn('npx', ['vite', 'preview', '--port', String(PORT)], {
    cwd: webDir,
    stdio: 'pipe',
    detached: false
  });

  preview.stderr.on('data', (d) => {
    // console.error('[preview err]', d.toString());
  });

  // Wait for preview server to be ready
  let serverReady = false;
  for (let i = 0; i < 30; i++) {
    try {
      const res = await fetch(`${BASE}/`);
      if (res.ok) {
        serverReady = true;
        break;
      }
    } catch {}
    await sleep(200);
  }

  if (!serverReady) {
    console.error('Preview server failed to start on', BASE);
    preview.kill();
    process.exit(1);
  }
  console.log('Preview server ready at', BASE);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  const errors = [];
  page.on('request', (r) => {
    if (r.url().includes('sources')) console.log('[REQ]', r.method(), r.url());
  });
  page.on('response', (r) => {
    if (r.url().includes('sources')) console.log('[RES]', r.status(), r.url());
  });

  try {
    // ----------------------------------------------------
    // ROUND TRIP 1: Load page & verify smart input focus
    // ----------------------------------------------------
    console.log('\n[Check 1] Page load and focus verification');
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await sleep(400);

    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      return el ? `${el.tagName}:${el.type || ''}` : 'none';
    });
    console.log('Active element on load:', focused);
    if (!focused.startsWith('TEXTAREA')) {
      throw new Error(`Expected TEXTAREA focused on load, got: ${focused}`);
    }
    console.log('PASS: smart input textarea is focused on load');

    // ----------------------------------------------------
    // ROUND TRIP 2: Add single link
    // ----------------------------------------------------
    console.log('\n[Check 2] Add single link');
    const input = page.locator('textarea.smart-input');
    await input.fill('https://example.com/article-1');
    await page.keyboard.press('Enter');
    await sleep(600);

    // Wait for card to appear
    const cards = page.locator('.source-tray-list .source-card');
    await cards.first().waitFor({ state: 'visible', timeout: 5000 });
    const count1 = await cards.count();
    console.log('Source cards count:', count1);
    if (count1 < 1) throw new Error('Expected at least 1 source card after adding link');

    const cardKind = await page.locator('.source-tray-list .kind-badge').first().textContent();
    console.log('Card kind badge:', cardKind?.trim());
    console.log('PASS: single link card added');

    // ----------------------------------------------------
    // ROUND TRIP 3: Add multiple links at once (one per line)
    // ----------------------------------------------------
    console.log('\n[Check 3] Add multiple links (one per line)');
    await input.focus();
    await input.fill('https://example.com/multi-a\nhttps://example.com/multi-b');
    await page.keyboard.press('Enter');
    await sleep(800);

    const count2 = await cards.count();
    console.log('Source cards count after multi-link:', count2);
    if (count2 !== 3) throw new Error(`Expected 3 cards, got ${count2}`);
    console.log('PASS: multiple links created individual cards');

    // ----------------------------------------------------
    // ROUND TRIP 4: Add plain text note
    // ----------------------------------------------------
    console.log('\n[Check 4] Add text note');
    await input.focus();
    await input.fill('Key takeaway: the DGX Spark runs all local AI inference at home.');
    await page.keyboard.press('Enter');
    await sleep(600);

    const count3 = await cards.count();
    console.log('Source cards count after note:', count3);
    if (count3 !== 4) throw new Error(`Expected 4 cards, got ${count3}`);

    const noteBadge = await page.locator('.source-tray-list .source-card').last().locator('.kind-badge').textContent();
    console.log('Last card badge:', noteBadge?.trim());
    if (noteBadge?.trim() !== 'note') throw new Error(`Expected 'note' badge, got ${noteBadge}`);
    console.log('PASS: plain text note card added');

    // ----------------------------------------------------
    // ROUND TRIP 5: File Upload via hidden file input
    // ----------------------------------------------------
    console.log('\n[Check 5] File upload');
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: 'Upload file' }).click();
    const fileChooser = await fileChooserPromise;

    const tmpFile = path.resolve(__dirname, 'test_sample.txt');
    fs.writeFileSync(tmpFile, 'Sample uploaded research document for vozonda source tray test.');
    await fileChooser.setFiles(tmpFile);
    fs.unlinkSync(tmpFile);
    await sleep(800);

    const count4 = await cards.count();
    console.log('Source cards count after upload:', count4);
    if (count4 !== 5) throw new Error(`Expected 5 cards, got ${count4}`);
    console.log('PASS: file uploaded and converted to source card');

    // ----------------------------------------------------
    // ROUND TRIP 6: Role toggle main/context
    // ----------------------------------------------------
    console.log('\n[Check 6] Role toggle main/context');
    const firstCard = page.locator('.source-tray-list .source-card').first();
    const contextBtn = firstCard.locator('.role-seg button', { hasText: 'context' });
    await contextBtn.click();
    await sleep(200);

    const isContextClass = await firstCard.evaluate((el) => el.classList.contains('card-context'));
    console.log('Card has card-context class:', isContextClass);
    if (!isContextClass) throw new Error('Expected card to have card-context class after selecting context');

    // Toggle back to main
    const mainBtn = firstCard.locator('.role-seg button', { hasText: 'main' });
    await mainBtn.click();
    await sleep(200);
    const isContextClassAfter = await firstCard.evaluate((el) => el.classList.contains('card-context'));
    if (isContextClassAfter) throw new Error('Expected card to not have card-context class after selecting main');
    console.log('PASS: role toggle works both ways');

    // ----------------------------------------------------
    // ROUND TRIP 7: Reload keeps tray (localStorage persistence)
    // ----------------------------------------------------
    console.log('\n[Check 7] Reload preserves tray');
    const storedBefore = await page.evaluate(() => localStorage.getItem('vozonda_tray_sources'));
    console.log('localStorage stored tray sources count:', JSON.parse(storedBefore || '[]').length);
    if (!storedBefore || JSON.parse(storedBefore).length !== 5) {
      throw new Error(`Expected 5 stored sources in localStorage, got: ${storedBefore}`);
    }

    await page.reload({ waitUntil: 'networkidle' });
    await sleep(800);

    const countReload = await page.locator('.source-tray-list .source-card').count();
    console.log('Cards after reload:', countReload);
    if (countReload !== 5) throw new Error(`Expected 5 cards after reload, got ${countReload}`);
    console.log('PASS: tray survived page reload');

    // ----------------------------------------------------
    // ROUND TRIP 8: Failing source & inline confirmation line
    // ----------------------------------------------------
    // Mock a failed source endpoint for failed-test-id on context level
    await context.route(/failed-test-id/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'failed-test-id',
          kind: 'article',
          origin_url: 'https://unreachable.example.com/broken-page',
          title: 'https://unreachable.example.com/broken-page',
          words: 0,
          chars: 0,
          status: 'failed',
          role: 'main',
          error: {
            code: 'unreachable',
            hint: 'server is unreachable or domain does not exist',
            retryable: true
          }
        })
      });
    });

    // Clear existing sources first
    while (await page.locator('.source-tray-list .source-card').count() > 0) {
      await page.locator('.source-tray-list .source-card .remove-btn').first().click();
      await sleep(150);
    }

    // Add a working source first
    await input.focus();
    await input.fill('Working primary note: everything is going smoothly.');
    await page.keyboard.press('Enter');
    await sleep(400);

    // Add failed-test-id to localStorage
    await page.evaluate(() => {
      const raw = localStorage.getItem('vozonda_tray_sources') || '[]';
      const list = JSON.parse(raw);
      list.push({ id: 'failed-test-id', role: 'main' });
      localStorage.setItem('vozonda_tray_sources', JSON.stringify(list));
    });

    await page.reload({ waitUntil: 'networkidle' });
    await sleep(800);

    const failedCard = page.locator('.source-tray-list .card-failed');
    await failedCard.waitFor({ state: 'visible', timeout: 3000 });
    const errorText = await failedCard.locator('.fail-hint').textContent();
    console.log('Failed card error text:', errorText?.trim());
    if (!errorText?.includes('server is unreachable')) {
      throw new Error(`Expected error hint to show, got: ${errorText}`);
    }

    const retryBtn = failedCard.locator('button.retry-btn');
    if (!(await retryBtn.isVisible())) {
      throw new Error('Expected retry button on failed card');
    }
    console.log('PASS: failed card shows error styling, hint, and retry button');

    // Test inline confirm line when clicking submit with failed source
    console.log('Testing inline confirm line on submit...');
    const submitBtn = page.locator('button.launch-btn');
    await submitBtn.click();
    await sleep(300);

    const confirmLine = page.locator('.fail-confirm-bar');
    if (!(await confirmLine.isVisible())) {
      throw new Error('Expected inline confirm bar to appear on first submit with failing source');
    }
    const confirmText = await confirmLine.textContent();
    console.log('Confirm bar text:', confirmText?.trim().replace(/\s+/g, ' '));
    if (!confirmText?.includes("1 source can't be read")) {
      throw new Error(`Unexpected confirm bar text: ${confirmText}`);
    }
    const bypassBtn = page.locator('.bypass-btn');
    const cancelBtn = page.locator('.cancel-bypass-btn');
    if (!(await bypassBtn.isVisible()) || !(await cancelBtn.isVisible())) {
      throw new Error('Expected bypass and cancel buttons in confirm bar');
    }
    console.log('PASS: inline confirm line displayed on first press with bypass/cancel options');

    // ----------------------------------------------------
    // ROUND TRIP 9: Citations in ScriptReview
    // ----------------------------------------------------
    console.log('\n[Check 9] ScriptReview [n] citations');
    await context.route(/jobs\/review-job-1$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'review-job-1',
          title: 'Citation Test Episode',
          state: 'awaiting_review',
          script: [
            { speaker: 'A', text: 'First line citing source 1.', src: [1] },
            { speaker: 'B', text: 'Second line citing sources 2 and 3.', src: [2, 3] },
            { speaker: 'A', text: 'Third line without citations.' }
          ],
          stages: [
            { name: 'fetch', status: 'done' },
            { name: 'extract', status: 'done' },
            { name: 'script', status: 'done', meta: { voice_map: { A: 'Ryan', B: 'Rachel' } } }
          ]
        })
      });
    });

    await page.goto(`${BASE}/#e=review-job-1`, { waitUntil: 'networkidle' });
    await sleep(800);

    const reviewSection = page.locator('section.review');
    await reviewSection.waitFor({ state: 'visible', timeout: 5000 });
    const badges = await reviewSection.locator('.src-badge').allTextContents();
    console.log('ScriptReview rendered citation badges:', badges);
    if (!badges.includes('[1]') || !badges.includes('[2]') || !badges.includes('[3]')) {
      throw new Error(`Expected [1], [2], [3] badges, found: ${badges.join(', ')}`);
    }
    console.log('PASS: [n] citations render correctly in ScriptReview');

    // ----------------------------------------------------
    // ROUND TRIP 10: Create Variant rebuilds tray
    // ----------------------------------------------------
    console.log('\n[Check 10] Create Variant (Remix) rebuilds tray');
    await context.route(/jobs\/done-job-1\/sources\/clone/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'cloned-1', kind: 'article', title: 'Cloned Article 1', words: 450, chars: 2800, status: 'ready', role: 'main' },
          { id: 'cloned-2', kind: 'note', title: 'Cloned Note 2', words: 120, chars: 700, status: 'ready', role: 'context' }
        ])
      });
    });

    await context.route(/jobs\/done-job-1$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'done-job-1',
          title: 'Finished Podcast',
          state: 'done',
          url: 'https://example.com/original-article',
          audio_seconds: 120,
          script: [
            { speaker: 'A', text: 'First dialogue line for audio player.' },
            { speaker: 'B', text: 'Second dialogue line responding.' }
          ],
          stages: [{ name: 'master', status: 'done' }]
        })
      });
    });

    // Navigate to done job
    await page.goto(`${BASE}/#e=done-job-1`, { waitUntil: 'networkidle' });
    await sleep(800);

    // Switch to facts tab where "create variant" pill lives
    const factsTab = page.locator('#tab-facts');
    if (await factsTab.isVisible()) {
      await factsTab.click();
      await sleep(200);
    }

    // Click "create variant" button in Player / Listen screen
    const variantBtn = page.locator('button', { hasText: 'create variant' }).first();
    await variantBtn.click({ force: true });
    await sleep(800);

    const variantCards = page.locator('.source-tray-list .source-card');
    await variantCards.first().waitFor({ state: 'visible', timeout: 5000 });
    const variantCount = await variantCards.count();
    console.log('Variant tray cards count:', variantCount);
    if (variantCount !== 2) throw new Error(`Expected 2 variant cards, got ${variantCount}`);
    const variantRole1 = await variantCards.first().locator('.role-seg button[aria-checked="true"]').textContent();
    const variantRole2 = await variantCards.last().locator('.role-seg button[aria-checked="true"]').textContent();
    console.log('Variant card 1 role:', variantRole1?.trim());
    console.log('Variant card 2 role:', variantRole2?.trim());
    if (variantRole1?.trim() !== 'main' || variantRole2?.trim() !== 'context') {
      throw new Error(`Expected roles main and context, got: ${variantRole1} and ${variantRole2}`);
    }
    console.log('PASS: create variant rebuilt tray via cloneJobSources');

    console.log('\n========================================');
    console.log('ALL 10 BROWSER ROUND TRIPS PASSED (GREEN)!');
    console.log('========================================\n');
  } finally {
    await browser.close();
    preview.kill();
  }
}

main().catch((err) => {
  console.error('FAILED:', err);
  process.exit(1);
});
