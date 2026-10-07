const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

// Budget in bytes: 60 KB = 60 * 1024 bytes (AGENTS.md hard rule 9)
const BUDGET_BYTES = 60 * 1024;

const distDir = path.resolve(__dirname, '../dist');
const indexPath = path.join(distDir, 'index.html');

if (!fs.existsSync(indexPath)) {
  console.error(`bundle_budget: ${indexPath} not found. Run 'npm run build' first.`);
  process.exit(1);
}

const html = fs.readFileSync(indexPath, 'utf8');

// Match <script ... src="...js"> tags referenced by index.html
const scriptTagRegex = /<script\s+[^>]*src=["']([^"']+\.js(?:\?[^"']*)?)["'][^>]*>/gi;
const scriptMatches = [];
let scriptMatch;
while ((scriptMatch = scriptTagRegex.exec(html)) !== null) {
  scriptMatches.push(scriptMatch[1]);
}

// Match <link rel="modulepreload" href="...js"> tags
const modulePreloadRegex = /<link\s+[^>]*rel=["']modulepreload["'][^>]*href=["']([^"']+\.js(?:\?[^"']*)?)["'][^>]*>/gi;
const preloadMatches = [];
let preloadMatch;
while ((preloadMatch = modulePreloadRegex.exec(html)) !== null) {
  preloadMatches.push(preloadMatch[1]);
}

const allScriptSrcs = [...scriptMatches, ...preloadMatches];

if (allScriptSrcs.length === 0) {
  console.error('bundle_budget: no entry JS script tags found in dist/index.html');
  process.exit(1);
}

console.log('Entry JS bundle budget check:');
let totalRaw = 0;
let totalGzip = 0;

for (const scriptSrc of allScriptSrcs) {
  const relPath = scriptSrc.replace(/^\//, '').replace(/\?.*$/, '');
  const filePath = path.join(distDir, relPath);

  if (!fs.existsSync(filePath)) {
    console.error(`bundle_budget: referenced file not found: ${filePath}`);
    process.exit(1);
  }

  const content = fs.readFileSync(filePath);
  const rawBytes = content.length;
  const gzipBytes = zlib.gzipSync(content, { level: 9 }).length;

  totalRaw += rawBytes;
  totalGzip += gzipBytes;

const rawKb = (rawBytes / 1024).toFixed(2);
    const gzipKb = (gzipBytes / 1024).toFixed(2);
    const kind = scriptMatches.includes(scriptSrc) ? 'script' : 'modulepreload';
    console.log(`  - ${kind} ${scriptSrc}: ${rawKb} KB (${gzipKb} KB gzip)`);
}

const totalRawKb = (totalRaw / 1024).toFixed(2);
const totalGzipKb = (totalGzip / 1024).toFixed(2);
const budgetKb = (BUDGET_BYTES / 1024).toFixed(2);

console.log(`Total entry JS: ${totalRawKb} KB raw, ${totalGzipKb} KB gzip (budget: ${budgetKb} KB)`);

if (totalGzip > BUDGET_BYTES) {
  const overKb = ((totalGzip - BUDGET_BYTES) / 1024).toFixed(2);
  console.error(`FAIL: Entry JS exceeds budget by ${overKb} KB (${totalGzipKb} KB > ${budgetKb} KB)`);
  process.exit(1);
} else {
  const underKb = ((BUDGET_BYTES - totalGzip) / 1024).toFixed(2);
  console.log(`PASS: Entry JS is within budget (${underKb} KB remaining under ${budgetKb} KB)`);
  process.exit(0);
}
