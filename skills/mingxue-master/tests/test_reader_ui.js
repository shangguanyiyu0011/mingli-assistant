'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const ui=path.resolve(__dirname,'../ui');

test('single-date board fills its row without empty columns or ornaments',()=>{
  const window={};vm.runInNewContext(fs.readFileSync(path.join(ui,'renderer.js'),'utf8'),{window});
  const html=window.MingRenderer.render({kind:'board',title:'择日',data:{columns:3,cells:[{label:'2030-01-01',value:'日表',items:['宜：出行']}]}});
  assert.match(html,/repeat\(1,minmax/);
  assert.doesNotMatch(html,/art-ornament|装饰图案|view-stamp|研习/);
});

test('known branch candidates are displayed instead of an unknown-hour label',()=>{
  const window={};vm.runInNewContext(fs.readFileSync(path.join(ui,'renderer.js'),'utf8'),{window});
  const html=window.MingRenderer.render({kind:'bazi_unknown',data:{columns:[{key:'hour',title:'时柱',values:['甲子','丙子'],certain:false}]}});
  assert.match(html,/甲子/);assert.match(html,/丙子/);assert.doesNotMatch(html,/时辰未定/);
});

test('parallel facts use escaped row headers and complete values',()=>{
  const window={};vm.runInNewContext(fs.readFileSync(path.join(ui,'renderer.js'),'utf8'),{window});
  const html=window.MingRenderer.metrics([{label:'历法日期',value:'2030-07-12'},{label:'农历',value:'示例农历年月日'},{label:'候选数',value:1},{label:'<img>',value:'<script>坏</script>'}]);
  assert.match(html,/<table class="data-table"/);
  assert.equal((html.match(/scope="row"/g)||[]).length,4);
  assert.match(html,/<td>示例农历年月日<\/td>/);
  assert.match(html,/<td>1<\/td>/);
  assert.match(html,/&lt;script&gt;/);
  assert.doesNotMatch(html,/<script>|<img>/);
});

test('all mansion names remain readable and the actual birth mansion is central',()=>{
  const window={};vm.runInNewContext(fs.readFileSync(path.join(ui,'renderer.js'),'utf8'),{window});
  const nodes=Array.from({length:27},(_,i)=>({label:'宿'+i,is_birth:i===1}));
  const html=window.MingRenderer.render({kind:'mansion',data:{nodes}});
  assert.equal((html.match(/font-size="18" font-weight=/g)||[]).length,27);
  assert.match(html,/font-size="48"[^>]*>宿1<\/text>/);
  assert.match(html,/本命宿/);
  assert.doesNotMatch(html,/undefined|NaN/);
});

test('report charts render on demand and all load before printing, then restore',()=>{
  const events={},clicks={},rendered=[];
  const node=id=>({id,hidden:false,open:false,innerHTML:'',dataset:{},classList:{toggle(){}},setAttribute(){},removeAttribute(){},addEventListener(type,fn){clicks[id+':'+type]=fn},scrollIntoView(){}});
  const root=node('report-app'),lead=node('overview'),theme=node('theme-A-分项解读-0');
  const sections=[node('panel-0'),node('panel-1')];sections.forEach(x=>x.open=true);
  const holders=[node('view-0'),node('view-1')],nav=[node('nav-0'),node('nav-1')];
  nav.forEach((x,i)=>x.dataset.section=String(i));
  root.querySelectorAll=selector=>selector==='.report-nav a[data-section]'?nav:selector==='details.panel'?sections:selector.includes('overview-lead')?[lead]:selector.includes('details.panel')?sections:[];
  root.querySelector=()=>lead;
  const data={kind:'personal',title:'合成测试',meta:{},people:[{name:'合成资料',birth:{date:'2000-01-01',time:null,shichen:'午'}}],overview:{scope:'A',summary:'综合内容',themes:[{title:'事业',text:'实际主题',basis:[]}]},panels:[0,1].map(i=>({system:i?'numerology':'bazi',title:'测试'+i,reader_available:true,interpretation:{text:'测试正文'},view:{kind:'numbers',data:{items:[]}}}))};
  data.people[0].photos=[{src:'data:image/png;base64,AA==',caption:'合成照片'},{src:'https://example.invalid/private.jpg',caption:'禁止远程照片'}];
  data.panels[0].illustrations=[{src:'data:image/png;base64,AA==',caption:'合成部位 & 观察'},{src:'data:image/svg+xml;base64,AA==',caption:'禁止SVG'}];
  data.overview.themes[0].basis=[{person:'A',system:'bazi',pointer:'/a'},{person:'A',system:'bazi',pointer:'/b'},{person:'A',system:'numerology',pointer:'/c'}];
  const nodes=new Map([root,lead,theme,node('report-print'),...sections,...holders].map(x=>[x.id,x]));
  nodes.set('report-data',{textContent:JSON.stringify(data)});
  const window={addEventListener:(name,fn)=>events[name]=fn,print(){}};
  vm.runInNewContext(fs.readFileSync(path.join(ui,'renderer.js'),'utf8'),{window});
  window.MingRenderer.render=view=>{rendered.push(view.system);return '图'};
  vm.runInNewContext(fs.readFileSync(path.join(ui,'report.js'),'utf8'),{window,document:{getElementById:id=>nodes.get(id)||null},console});
  assert.equal(rendered.length,0);
  assert.match(root.innerHTML,/<th scope="row">出生时辰<\/th><td>午时<\/td>/);
  assert.doesNotMatch(root.innerHTML,/report-brand|命学总助手/);
  assert.equal((root.innerHTML.match(/data-basis-panel="0"/g)||[]).length,1);
  assert.equal((root.innerHTML.match(/data-basis-panel="1"/g)||[]).length,1);
  assert.match(root.innerHTML,/AI分析示意图 · 合成部位 &amp; 观察/);
  assert.doesNotMatch(root.innerHTML,/禁止SVG|data:image\/svg/);
  assert.match(root.innerHTML,/class="reader-photo"/);
  assert.match(root.innerHTML,/alt="合成照片"/);
  assert.doesNotMatch(root.innerHTML,/example\.invalid|禁止远程照片/);
  const openPanel=index=>clicks['report-app:click']({preventDefault(){},target:{closest:s=>s==='a[data-basis-panel]'?{dataset:{basisPanel:String(index)}}:null}});
  openPanel(0);openPanel(0);assert.deepEqual(rendered,['bazi']);
  const oldState=sections.map(x=>[x.hidden,x.open]);
  events.beforeprint();assert.deepEqual(rendered,['bazi','numerology']);
  assert.ok(sections.every(x=>!x.hidden&&x.open));
  events.afterprint();assert.deepEqual(sections.map(x=>[x.hidden,x.open]),oldState);
  assert.equal(lead.hidden,true);
});

test('original photo annotations keep exact source and escaped observations, unsafe overlays reveal no photo',()=>{
  const render=illustrations=>{
    const root={innerHTML:'',querySelectorAll(){return []},querySelector(){return null},addEventListener(){}};
    const data={kind:'personal',title:'原图标注测试',meta:{},people:[],overview:{summary:'综合内容'},panels:[{system:'palm',title:'手相',reader_available:true,interpretation:{text:'实际观察'},illustrations}]};
    const window={addEventListener(){},print(){}},nodes={'report-app':root,'report-data':{textContent:JSON.stringify(data)},'report-print':{addEventListener(){}}};
    vm.runInNewContext(fs.readFileSync(path.join(ui,'renderer.js'),'utf8'),{window});
    vm.runInNewContext(fs.readFileSync(path.join(ui,'report.js'),'utf8'),{window,document:{getElementById:id=>nodes[id]||null}});
    return root.innerHTML;
  };
  const photo={kind:'photo_annotation',src:'data:image/jpeg;base64,/9j/AA==',caption:'本人掌照',overlay:{width:800,height:600,annotations:[{region:'thumb_arc',label:'弧线 <img> & 部位',observation:'只标可见 <script>坏</script> 的一段。',geometry:'polyline',points:[[100,120],[200,250],[300,400]]}]}};
  const html=render([photo,{src:'data:image/png;base64,AA==',caption:'独立示意图'},{src:'data:image/png;base64,AA==',caption:'本人照片模型标注',kind:'generated_photo_annotation',source_photo_id:'a'}]);
  assert.match(html,/src="data:image\/jpeg;base64,\/9j\/AA=="/);
  assert.match(html,/viewBox="0 0 800 600"/);assert.match(html,/<polyline points="100,120 200,250 300,400"/);
  assert.match(html,/<circle cx="100" cy="120"/);assert.match(html,/原图标注 · 本人掌照/);
  assert.match(html,/弧线 &lt;img&gt; &amp; 部位/);assert.match(html,/&lt;script&gt;坏&lt;\/script&gt;/);
  assert.match(html,/AI分析示意图 · 独立示意图/);assert.doesNotMatch(html,/AI分析示意图 · 本人掌照|<script>|<img>/);
  assert.match(html,/原图AI标注 · 本人照片模型标注/);assert.doesNotMatch(html,/AI分析示意图 · 本人照片模型标注/);
  for(const change of [{width:0},{width:Infinity},{annotations:[{...photo.overlay.annotations[0],geometry:'script'}]},
      {annotations:[{...photo.overlay.annotations[0],region:'face_outline'}]},
      {annotations:[{...photo.overlay.annotations[0],points:[[true,2],[3,4]]}]},
      {annotations:[{...photo.overlay.annotations[0],points:[[900,2],[3,4]]}]}]){
    const rejected=render([{...photo,overlay:{...photo.overlay,...change}}]);
    assert.doesNotMatch(rejected,/本人掌照|data:image\/jpeg|photo-annotation-frame/);
  }
});

test('four report locales translate chrome and chart fields while preserving authored text and names',()=>{
  const dictionaries=JSON.parse(fs.readFileSync(path.join(ui,'report-locales.json'),'utf8'));
  for(const language of ['zh-CN','en','ja','ko']){
    const root={innerHTML:'',querySelectorAll(){return []},querySelector(){return null},addEventListener(){}};
    const authored='Original 원문 日本語 行动建议 <keep> & text';
    const data={kind:'personal',language,title:'Owner 行动建议',meta:{question:authored},people:[{name:'行动建议',notes:authored}],
      overview:{summary:authored,themes:[{title:authored,text:authored}],actions:[{title:authored,text:authored}]},
      panels:[{system:'names',title:'姓名学',reader_available:true,interpretation:{text:authored}}]};
    const window={MINGXUE_LOCALES:dictionaries,addEventListener(){},print(){}},nodes={'report-app':root,'report-data':{textContent:JSON.stringify(data)},'report-print':{addEventListener(){}}};
    const context={window,document:{getElementById:id=>nodes[id]||null}};
    for(const file of ['i18n.js','renderer.js','report.js'])vm.runInNewContext(fs.readFileSync(path.join(ui,file),'utf8'),context);
    const t=value=>window.MingxueI18n.t(value,null,language);
    assert.match(root.innerHTML,new RegExp(t('导出 PDF').replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
    assert.ok(root.innerHTML.includes(t('报告目录')));
    assert.ok(root.innerHTML.includes('Original 원문 日本語 行动建议 &lt;keep&gt; &amp; text'));
    assert.ok(root.innerHTML.includes('<h2>行动建议'));
    const chart=window.MingRenderer.render({kind:'numbers',title:'姓名学',data:{items:[{label:'完整姓名',value:'行动建议',literal:true},{label:'姓名表达数',value:3}]}});
    assert.ok(chart.includes(t('完整姓名')));assert.ok(chart.includes(t('姓名表达数')));
    assert.ok(chart.includes('>行动建议</div>'));assert.ok(chart.includes('>3</div>'));
    assert.equal(data.people[0].name,'行动建议');assert.equal(data.panels[0].title,'姓名学');
  }
});

test('wheel print layout uses the same stable selector in every report language',()=>{
  const dictionaries=JSON.parse(fs.readFileSync(path.join(ui,'report-locales.json'),'utf8'));
  const css=fs.readFileSync(path.join(ui,'report.css'),'utf8');
  assert.equal((css.match(/\.chart\[data-view-kind="wheel"\]/g)||[]).length,3);
  assert.doesNotMatch(css,/aria-label="占星黄经盘面"/);
  for(const language of ['zh-CN','en','ja','ko']){
    const window={MINGXUE_LOCALES:dictionaries,MingxueReportLanguage:language};
    for(const file of ['i18n.js','renderer.js'])vm.runInNewContext(fs.readFileSync(path.join(ui,file),'utf8'),{window});
    const chart=window.MingRenderer.render({kind:'wheel',data:{points:[{name:'太阳',longitude:15}]}});
    assert.match(chart,/<div class="chart" data-view-kind="wheel">/);
    const label=window.MingxueI18n.t('占星黄经盘面',null,language);
    assert.ok(chart.includes(`aria-label="${label}"`));
  }
});
