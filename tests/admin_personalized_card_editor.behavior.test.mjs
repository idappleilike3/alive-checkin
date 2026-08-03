import assert from 'node:assert/strict';
import fs from 'node:fs';

const html = fs.readFileSync(new URL('../admin.html', import.meta.url), 'utf8');

assert.match(html, /圖文卡設定與預覽/);
assert.match(html, /步驟 1[\s\S]*載入可推播會員/);
assert.match(html, /步驟 2[\s\S]*選擇會員/);
assert.match(html, /步驟 3[\s\S]*預覽這位會員的圖片卡/);
assert.match(html, /id="personalizedSingleBtn"[^>]*disabled/);
assert.match(html, /id="personalizedSendAllBtn"[^>]*hidden/);
assert.match(html, /節日背景生成器/);
assert.match(html, /使用節日範本/);
assert.match(html, /幫我自動生成/);
assert.match(html, /daily-peace-logo\.png/);
assert.match(html, /id="cardBlessingFont"/);
assert.match(html, /id="cardBlessingColor"/);
assert.match(html, /id="cardBlessingSize"/);
assert.match(html, /id="cardBlessingAlign"/);
assert.match(html, /id="cardBlessingPosition"/);
assert.match(html, /aspect-ratio:\s*4\s*\/\s*5/);
assert.match(html, /#D4A017/i);
assert.match(html, /@media\s*\(max-width:\s*760px\)[\s\S]*card-editor-grid/);
console.log('admin personalized card editor behavior passed');
