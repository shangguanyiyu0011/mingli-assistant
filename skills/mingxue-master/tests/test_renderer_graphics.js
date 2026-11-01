const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const window = {};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../ui/renderer.js'), 'utf8'), { window });
const data = { figures: [
  { id: 'M1', name: '母一 · 众', row: 0, col: 0, points: [2,2,2,2], parents: [] },
  { id: 'D1', name: '女一 · 龙首', row: 0, col: 1, points: [2,1,1,1], parents: ['M1'] },
  { id: 'N1', name: '侄一 · <白>', row: 1, col: 0.5, points: [2,2,1,2], parents: ['M1','D1'] }
] };
const before = JSON.stringify(data);
const shield = window.MingRenderer.render({ kind: 'shield', data });
const svg = shield.match(/<svg[\s\S]*?<\/svg>/)[0];
assert.equal(JSON.stringify(data), before, 'Rendering must retain the actual figures and derivation');
assert.equal((svg.match(/<circle /g) || []).length, 20, 'Every original single/double point stays visible');
assert.equal((svg.match(/class="shield-node-bg"/g) || []).length, 3);
assert(svg.lastIndexOf('<line ') < svg.indexOf('class="shield-node-bg"'), 'Derivation lines stay behind opaque figure labels');
assert(svg.lastIndexOf('<path ') < svg.indexOf('class="shield-node-bg"'), 'Same-row links stay behind figure labels');
assert(svg.includes('侄一 · &lt;白&gt;') && !svg.includes('侄一 · <白>'), 'Figure titles remain escaped');
const cards = window.MingRenderer.render({ kind:'cards', system:'lenormand', data:{cards:[{id:1,label:'骑士'}],columns:1} });
assert(!cards.includes('正位') && !cards.includes('逆位') && !cards.includes('undefined'));
const tarot = window.MingRenderer.render({kind:'cards',system:'tarot',data:{cards:[{id:'cups-ace',label:'圣杯首牌',orientation:'reversed'}],columns:1}});
assert(tarot.includes('逆位'), 'Actual tarot reversals remain displayed');
process.stdout.write('PASS: shield labels protected, point data retained, Lenormand/Tarot orientation separated\n');
