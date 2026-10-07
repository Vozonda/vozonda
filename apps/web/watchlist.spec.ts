import { test, expect } from '@playwright/test';

test('watchlist', async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto('http://localhost:5173/#watchlist');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/tmp/watchlist_home.png', fullPage: true });
  
  const bodyText = await page.textContent('body');
  console.log('=== BODY TEXT ===');
  console.log(bodyText);
  console.log('=================');
  
  const buttons = await page.$$eval('button', bs => bs.map(b => b.textContent?.trim()).filter(Boolean));
  console.log('\n=== BUTTONS ===');
  console.log(buttons);
  console.log('===============');
  
  const h2s = await page.$$eval('h2', hs => hs.map(h => h.textContent?.trim()).filter(Boolean));
  console.log('\n=== H2 HEADINGS ===');
  console.log(h2s);
  console.log('=================');
  
  const settingsEl = await page.$('button:has-text("settings")');
  if (settingsEl) {
    await settingsEl.click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: '/tmp/watchlist_settings_open.png', fullPage: true });
    
    const bodyText2 = await page.textContent('body');
    console.log('\n=== AFTER CLICK SETTINGS ===');
    console.log(bodyText2);
    console.log('=================');
    
    const buttons2 = await page.$$eval('button', bs => bs.map(b => b.textContent?.trim()).filter(Boolean));
    console.log('\n=== BUTTONS AFTER ===');
    console.log(buttons2);
    console.log('===================');
  }
  
  await page.close();
});
