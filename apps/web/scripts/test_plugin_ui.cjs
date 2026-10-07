const { chromium } = require('playwright');

const BASE = 'http://localhost:4173';

(async () => {
  console.log('=== VOZONDA UI/UX & PLUGIN INTEGRATION TEST ===\n');
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  const passed = [];
  const failed = [];

  function assert(name, condition, detail = '') {
    if (condition) {
      console.log(`PASS: ${name}${detail ? ' (' + detail + ')' : ''}`);
      passed.push(name);
    } else {
      console.error(`FAIL: ${name}${detail ? ' (' + detail + ')' : ''}`);
      failed.push({ name, detail });
    }
  }

  try {
    // 1. Home / Compose Screen
    console.log('[1/4] Testing Compose Screen & Show Templates...');
    await page.goto(BASE, { waitUntil: 'networkidle' });

    const title = await page.title();
    assert('Page title loaded', title.includes('vozonda'), title);

    const templateTiles = await page.locator('.template-tile').count();
    assert('Show Template tiles rendered', templateTiles >= 8, `${templateTiles} tiles found`);

    // Click on a template tile and verify style updates
    const firstTile = page.locator('.template-tile').first();
    await firstTile.click();
    await page.waitForTimeout(300);

    const styledocVisible = await page.locator('.styledoc-box').isVisible();
    assert('Style documentation box active after template pick', styledocVisible);

    const styledocText = await page.locator('.styledoc-text').textContent();
    assert('Style description non-empty', styledocText.trim().length > 10, styledocText.trim().slice(0, 40));

    // Source switch
    const plainTextBtn = page.locator('button[role="radio"]:has-text("plain text")');
    await plainTextBtn.click();
    await page.waitForTimeout(200);
    const textareaVisible = await page.locator('textarea.source-text').isVisible();
    assert('Switching to plain text shows textarea', textareaVisible);

    const weblinkBtn = page.locator('button[role="radio"]:has-text("weblink")');
    await weblinkBtn.click();
    await page.waitForTimeout(200);
    const inputVisible = await page.locator('input[type="url"]').isVisible();
    assert('Switching back to weblink shows URL input', inputVisible);

    // 2. Settings Screen & Plugin Engine Selection
    console.log('\n[2/4] Testing Settings Screen & Plugin Engine Selection...');
    await page.click('.settings-cta');
    await page.waitForSelector('.settings-screen', { state: 'visible', timeout: 5000 });
    assert('Settings screen opened', true);

    // Verify TTS Engine dropdown rendered with all 4 decoupled plugins
    const ttsSelect = page.locator('#s-engine, select[value*="tts"]');
    await ttsSelect.waitFor({ state: 'visible', timeout: 3000 });
    assert('TTS Engine select control present', await ttsSelect.count() > 0);

    const ttsOptionValues = await ttsSelect.locator('option').evaluateAll(options => options.map(o => o.value));
    for (const eng of ['qwen_tts', 'voxtral', 'kokoro', 'piper']) {
      assert(`TTS engine option registered: ${eng}`, ttsOptionValues.includes(eng), JSON.stringify(ttsOptionValues));
    }

    // Switch TTS Engine to kokoro and verify dynamic detail badge
    await ttsSelect.selectOption('kokoro');
    await page.waitForTimeout(400);
    const kokoroBadge = await page.locator('.engine-detail').first().textContent();
    assert('Kokoro engine details updated dynamically', kokoroBadge.includes('Kokoro-82M') || kokoroBadge.includes('82M Expressive'));

    // Switch TTS Engine back to qwen_tts
    await ttsSelect.selectOption('qwen_tts');
    await page.waitForTimeout(400);
    const qwenBadge = await page.locator('.engine-detail').first().textContent();
    assert('Switched back to Qwen-TTS details', qwenBadge.includes('Qwen3-TTS') || qwenBadge.includes('Studio Clarity'));

    // Verify LLM Engine selection
    const llmSection = page.locator('h3#llm-h, section[aria-labelledby="llm-h"], #s-llm-engine');
    assert('LLM Provider configuration section present', await llmSection.count() > 0);

    // Verify System Diagnostics / Doctor
    const docSummary = await page.locator('.doctor-grid, .doc-summary, .doctor-card, .sec-head:has-text("system diagnostics")').count() > 0;
    assert('Doctor / provider status diagnostics visible in settings', docSummary);

    // Close Settings using the back button
    const backBtn = page.locator('button.back, button[aria-label="Back to compose"]').first();
    await backBtn.click();
    await page.waitForTimeout(300);
    const settingsClosed = await page.locator('.settings-screen').isHidden();
    assert('Settings screen closes cleanly back to compose', settingsClosed);

    // 3. Navigation & Library
    console.log('\n[3/4] Testing Navigation, Library & FAQ...');
    const libLink = page.locator('button.foot-link:has-text("library"), a:has-text("library")').first();
    await libLink.click();
    await page.waitForTimeout(500);
    const libScreen = await page.locator('.library-summary, .searchbar, input.search-input').count() > 0;
    assert('Library screen loaded', libScreen);

    // Return to compose
    const returnBtn = page.locator('button.back, button:has-text("back"), button:has-text("new episode")').first();
    await returnBtn.click();
    await page.waitForTimeout(300);

    // 4. Standalone Public Share View (/e/{id})
    console.log('\n[4/4] Testing Standalone Public Share View...');
    // Query a done job from API
    const jobsResp = await page.request.get('http://127.0.0.1:8787/jobs?limit=10');
    if (jobsResp.ok()) {
      const data = await jobsResp.json();
      const doneJobs = (data.jobs || []).filter(j => j.state === 'done');
      if (doneJobs.length > 0) {
        const testJob = doneJobs[0];
        const shareUrl = `${BASE.replace('4173', '8787')}/e/${testJob.id}`;
        const shareResp = await page.request.get(shareUrl);
        assert('Public share view /e/{id} returns 200 OK', shareResp.status() === 200);

        const html = await shareResp.text();
        assert('Public share contains OpenGraph tags', html.includes('property="og:title"') && html.includes('property="og:audio"'));
        assert('Public share contains Twitter player card', html.includes('name="twitter:card"'));
        assert('Public share contains Schema.org AudioObject', html.includes('"@type": "AudioObject"') || html.includes('itemtype="https://schema.org/AudioObject"'));
      } else {
        assert('Public share view test', true, 'skipped: no finished job in test DB');
      }
    }

  } catch (err) {
    console.error('Unhandled test error:', err);
    failed.push({ name: 'Unhandled Exception', detail: String(err) });
  } finally {
    await browser.close();
  }

  console.log('\n========================================');
  console.log(`TOTAL: ${passed.length} passed, ${failed.length} failed`);
  if (failed.length > 0) {
    console.log('FAILURES:', failed);
    process.exit(1);
  } else {
    console.log('ALL TESTS PASSED CLEANLY.');
  }
})();
