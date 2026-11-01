'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const {performance}=require('node:perf_hooks');
const root=process.env.MINGXUE_TEST_SKILL_ROOT || path.resolve(__dirname,'..');
const source=fs.readFileSync(process.env.MINGXUE_DRAWS_SOURCE||path.join(root,'ui/intake-draws.js'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const QUESTION='我该怎样安排这个月的学习和沟通？';
let passed=0;
class Element {
  constructor(tag,doc){this.nodeType=1;this.tagName=tag;this.ownerDocument=doc;this.children=[];this.listeners={};this.dataset={};this.style=new Proxy({setProperty:(key,value)=>{this.style[key]=value;},removeProperty:key=>{delete this.style[key];}},{set:(target,key,value)=>{if(key==='backgroundImage'||key==='--mx-draw-back')doc.metrics.styleImageBytes+=String(value).length;target[key]=value;return true;}});this.attributes={};this.className='';this._text='';this._disabled=false;this.hidden=false;this.value='';this.checked=false;this.open=false;this.classList={add:name=>{this.className+=' '+name;}};}
  get childNodes(){return this.children;}
  appendChild(child){if(child.parentElement){const siblings=child.parentElement.children,index=siblings.indexOf(child);if(index>=0)siblings.splice(index,1);}this.children.push(child);child.parentElement=this;return child;}
  replaceChild(child,old){this.ownerDocument.metrics.replaceChild++;const index=this.children.indexOf(old);assert.ok(index>=0);this.children[index]=child;child.parentElement=this;old.parentElement=null;return old;}
  querySelector(selector){for(const child of this.children){if(selector.startsWith('.')?child.className.split(' ').includes(selector.slice(1)):child.tagName===selector)return child;const found=child.querySelector(selector);if(found)return found;}return null;}
  replaceChildren(...children){this.ownerDocument.metrics.replaceChildren++;for(const child of this.children)child.parentElement=null;this.children=[];for(const child of children)this.appendChild(child);}
  set disabled(value){this.ownerDocument.metrics.disabledWrites++;this._disabled=value;}
  get disabled(){return this._disabled;}
  set src(value){this.ownerDocument.metrics.imageSrcBytes+=String(value).length;this._src=value;}
  get src(){return this._src;}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  setAttribute(key,value){this.attributes[key]=String(value);}
  getAttribute(key){return this.attributes[key]??null;}
  addEventListener(type,listener){(this.listeners[type]??=[]).push(listener);}
  fire(type){if(type==='click'&&this.disabled)return;for(const listener of this.listeners[type]||[])listener({target:this,currentTarget:this});}
}
class Document{constructor(){this.created=0;this.metrics={disabledWrites:0,styleImageBytes:0,imageSrcBytes:0,replaceChildren:0,replaceChild:0,jsonImageBytes:0};}createElement(tag){this.created++;return new Element(tag,this);}}
function setup(options={}){
  const doc=new Document(),host=doc.createElement('div');let calls=0,counter=0x9e3779b9,queue=options.queue?options.queue.slice():[];
  const math=Object.create(Math);math.random=()=>{throw Error('Forbidden non-crypto randomness');};
  const crypto={getRandomValues(array){calls++;if(options.real)return webcrypto.getRandomValues(array);let value;if(queue.length)value=queue.shift();else if(options.constant!==undefined)value=options.constant;else{counter^=counter<<13;counter^=counter>>>17;counter^=counter<<5;value=counter>>>0;}array[0]=value>>>0;return array;}};
  const json=Object.create(JSON);json.stringify=(value,...args)=>{if(typeof value==='string'&&value.startsWith('data:image/'))doc.metrics.jsonImageBytes+=value.length;return JSON.stringify(value,...args);};
  const context={crypto,Math:math,Uint32Array,Set,Map,console,JSON:json};context.window=context;context.globalThis=context;
  if(options.i18n){doc.body=host;doc.documentElement={};context.document=doc;context.MINGXUE_LOCALES=JSON.parse(fs.readFileSync(path.join(root,'ui/intake-locales.json'),'utf8'));vm.runInNewContext(fs.readFileSync(path.join(root,'ui/i18n.js'),'utf8'),context);context.MingxueI18n.setLanguage(options.language||'zh-CN');}
  vm.runInNewContext(source,context,{filename:'intake-draws.js'});
  const api=context.MingxueDraws;api.init(host,options.config||{});
  const nodes=()=>{const out=[];function walk(node){out.push(node);for(const child of node.children)walk(child);}walk(host);return out;};
  const find=criteria=>nodes().find(node=>Object.entries(criteria).every(([key,value])=>node.dataset[key]===String(value)));
  const click=(system,action,slot)=>{const target=find({system,action,...(slot===undefined?{}:{slot})});assert.ok(target,system+' '+action+' exists');target.fire('click');};
  const select=(system,control,value)=>{const target=find({system,control});assert.ok(target);target.value=value;target.fire('change');};
  return {api,host,context,nodes,find,click,select,calls:()=>calls,created:()=>doc.created,metrics:doc.metrics,setQueue:value=>{queue=value.slice();}};
}
function test(name,fn){fn();passed++;}
function base(pair=false){const p={person:{name:'抽取合成甲'},birth:{date:'2000-08-16',time:null,calendar:'solar',timezone:'Asia/Shanghai'}};return {mode:pair?'pair':'single',people:pair?[p,{person:{name:'抽取合成乙'},birth:{date:'1997-03-24',time:null,calendar:'solar',timezone:'Asia/Shanghai'}}]:[p],preferences:{systems:['tarot','lenormand','iching','yilin','lingqijing','geomancy'],question:QUESTION,virtual_draws:false,answers:{}},method_options:{}};}
function finishCards(env,id,count){env.click(id,'start');for(let slot=0;slot<count;slot++)env.click(id,'pick',slot);}
function finishRows(env,id,count){env.click(id,'start');for(let row=0;row<count;row++)env.click(id,'toss');}

function measureLargeArt(){
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'assets/art-manifest.json'),'utf8'));
  const art=Object.fromEntries(manifest.assets.map(asset=>[asset.key,{...asset,src:'data:image/png;base64,'+fs.readFileSync(path.join(root,asset.file||asset.path)).toString('base64')}]));
  const e=setup({config:{art}});e.api.update('all',{question:QUESTION});
  const steps=[];
  for(const [action,slot]of [['start'],['pick',0],['pick',1],['pick',2]]){
    const target=e.find({system:'tarot',action,...(slot===undefined?{}:{slot})}),prior={...e.metrics,created:e.created()},hostChildren=e.host.children.slice(),other=e.find({system:'lenormand'});
    const before=performance.now();target.fire('click');const elapsed_ms=performance.now()-before;
    steps.push({action:slot===undefined?'shuffle':'pick-'+(slot+1),elapsed_ms,...Object.fromEntries(Object.entries({...e.metrics,created:e.created()}).map(([key,value])=>[key,value-prior[key]])),host_preserved:hostChildren.every((node,i)=>e.host.children[i]===node),other_method_preserved:e.find({system:'lenormand'})===other});
  }
  return {card_back_file_bytes:fs.statSync(path.join(root,'assets/art/card_back.png')).size,steps};
}
if(process.env.MINGXUE_DRAW_MEASURE_ONLY){process.stdout.write(JSON.stringify(measureLargeArt()));process.exit(0);}

test('init update skipped apply do not randomize',()=>{
  const e=setup();e.api.update('all',{pair:false,question:QUESTION});const request=base();const result=e.api.apply(request,'all');
  assert.equal(e.calls(),0);assert.deepEqual(plain(result),request);assert.notEqual(result,request);
  assert.doesNotMatch(source,/Math\s*\.\s*random\s*\(/);assert.match(source,/getRandomValues/);
});
test('a clear question is required before any randomness',()=>{
  const e=setup();e.api.update(['tarot'],{question:'  ？  '});e.click('tarot','start');assert.equal(e.calls(),0);assert.equal(e.api.getState().methods.tarot.started,false);assert.match(e.host.textContent,/请先/);
});
test('question and people updates preserve card DOM and never redraw or randomize',()=>{
  const e=setup();e.api.update('all',{question:QUESTION});e.click('tarot','start');e.click('lenormand','start');
  const card=e.find({system:'tarot',action:'pick',slot:2}),before=e.created(),random=e.calls();
  for(let i=0;i<30;i++)e.api.update('all',{question:QUESTION+i,pair:i%2===0});
  assert.equal(e.created(),before);assert.equal(e.calls(),random);assert.equal(e.find({system:'tarot',action:'pick',slot:2}),card);
});
test('picking one card preserves all other deck nodes and only builds one card',()=>{
  const e=setup();e.api.update('all',{question:QUESTION});e.click('tarot','start');e.click('lenormand','start');
  const sameDeck=e.find({system:'tarot',action:'pick',slot:2}),otherDeck=e.find({system:'lenormand',action:'pick',slot:0}),before=e.created();
  e.click('tarot','pick',0);assert.equal(e.find({system:'tarot',action:'pick',slot:2}),sameDeck);assert.equal(e.find({system:'lenormand',action:'pick',slot:0}),otherDeck);assert.ok(e.created()-before<15);
});
test('the actual third pick completes in place and retains clicked order without disabling 78 cards',()=>{
  const e=setup();e.api.update('all',{question:QUESTION});e.click('tarot','start');e.click('lenormand','start');
  e.click('tarot','pick',40);e.click('tarot','pick',2);
  const pool=e.find({system:'tarot',action:'pick',slot:40}).parentElement,first=pool.children[40],second=pool.children[2],remaining=pool.children[9],method=pool.parentElement.parentElement,other=e.find({system:'lenormand'}),hostChildren=e.host.children.slice(),before=e.created(),disabled=e.metrics.disabledWrites;
  e.click('tarot','pick',77);
  assert.equal(e.created()-before,5);assert.equal(e.metrics.disabledWrites-disabled,1);
  assert.equal(pool.parentElement.parentElement,method);assert.deepEqual(e.host.children,hostChildren);assert.equal(e.find({system:'lenormand'}),other);
  assert.deepEqual(pool.children.map(node=>Number(node.dataset.slot)),[40,2,77]);assert.equal(pool.children[0],first);assert.equal(pool.children[1],second);
  assert.equal(pool.children.length,3);assert.equal(pool.style['--mx-draw-back'],undefined);
  assert.deepEqual(plain(e.api.apply(base(),['tarot'])).method_options.tarot.cards,e.api.getState().methods.tarot.picked.map(card=>card.id+':'+card.orientation));
  const state=plain(e.api.getState()),nodes=e.created(),random=e.calls();remaining.fire('click');remaining.fire('click');first.fire('click');assert.deepEqual(plain(e.api.getState()),state);assert.equal(e.created(),nodes);assert.equal(e.calls(),random);
});
test('completed Lenormand layouts display the selected sequence and survive subsequent updates',()=>{
  for(const [spread,count,layouts]of [['pair',2,['line']],['three',3,['line']],['nine',9,['3x3']],['grand',36,['9x4','8x4+4']]])for(const layout of layouts){
    const e=setup();e.api.update('all',{question:QUESTION});e.select('lenormand','spread',spread);if(spread==='grand')e.select('lenormand','layout',layout);
    e.click('lenormand','start');const positions=Array.from({length:count},(_,i)=>35-i);for(const slot of positions)e.click('lenormand','pick',slot);
    const panel=e.find({system:'lenormand'}),pool=panel.querySelector('.mx-draw-pool'),picked=panel.querySelector('.mx-draw-picked'),state=plain(e.api.getState().methods.lenormand),random=e.calls(),created=e.created();
    assert.equal(pool.dataset.layout,layout);assert.equal(pool.children.length,count);assert.deepEqual(pool.children.map(card=>Number(card.dataset.slot)),positions);
    for(let i=0;i<count;i++){assert.match(pool.children[i].textContent,new RegExp('第'+(i+1)+'张'));assert.equal(picked.children[i].textContent,state.picked[i].name);assert.match(pool.children[i].textContent,new RegExp(state.picked[i].name));}
    e.api.update('all',{pair:true,question:'更改后保留原来的问题和牌序。'});assert.equal(e.created(),created);assert.equal(e.calls(),random);assert.equal(panel.querySelector('.mx-draw-pool'),pool);assert.deepEqual(plain(e.api.getState().methods.lenormand),state);
    e.api.update(['tarot'],{pair:false,question:QUESTION});e.api.update('all',{pair:false,question:QUESTION});const rebuilt=e.find({system:'lenormand'}).querySelector('.mx-draw-pool');assert.equal(rebuilt.dataset.layout,layout);assert.deepEqual(rebuilt.children.map(card=>Number(card.dataset.slot)),positions);assert.equal(e.calls(),random);
    assert.deepEqual(plain(e.api.apply(base(),['lenormand'])).method_options.lenormand.cards,state.picked.map(card=>card.number));
  }
  const css=fs.readFileSync(path.join(root,'ui/intake-draws.css'),'utf8');assert.match(css,/data-layout="9x4"[^}]*repeat\(9,/);assert.match(css,/data-layout="8x4\+4"[^}]*repeat\(8,/);assert.match(css,/nth-child\(33\)\{grid-column:3\}/);
});
test('layout changes require a new draw and skip clears only the chosen method without randomness',()=>{
  const e=setup();e.api.update('all',{question:QUESTION});finishCards(e,'tarot',3);e.select('lenormand','spread','grand');e.select('lenormand','layout','8x4+4');finishCards(e,'lenormand',36);
  const old=plain(e.api.getState().methods.lenormand),tarot=plain(e.api.getState().methods.tarot),random=e.calls();e.select('lenormand','layout','9x4');assert.deepEqual(plain(e.api.getState().methods.lenormand),old);
  e.click('lenormand','skip');assert.equal(e.calls(),random);assert.equal(e.api.getState().methods.lenormand.started,false);assert.deepEqual(plain(e.api.getState().methods.tarot),tarot);
  e.select('lenormand','layout','9x4');e.click('lenormand','start');assert.ok(e.calls()>random);assert.equal(e.api.getState().methods.lenormand.layout,'9x4');assert.equal(e.find({system:'lenormand'}).querySelector('.mx-draw-pool').children.length,36);
  const first=e.api.getState().methods.lenormand;e.click('lenormand','pick',8);const before=e.calls();e.click('lenormand','start');assert.ok(e.calls()>before);assert.equal(e.api.getState().methods.lenormand.picked.length,0);assert.equal(e.api.getState().methods.lenormand.question,first.question);
});
test('unsupported five-card Lenormand is not exposed or accepted by the selector',()=>{
  const e=setup();e.api.update(['lenormand'],{question:QUESTION});assert.equal(e.api.getCatalog().lenormandSpreads.five,undefined);e.select('lenormand','spread','five');assert.equal(e.api.getState().methods.lenormand.spread,'three');finishCards(e,'lenormand',3);assert.equal(e.api.apply(base(),['lenormand']).method_options.lenormand.spread,'three');
});
test('offline-sized real artwork is shared once and final selection never copies card backs',()=>{
  const measured=measureLargeArt();assert.ok(measured.steps[0].jsonImageBytes<6000000);assert.ok(measured.steps[0].styleImageBytes<6000000);
  for(const step of measured.steps.slice(1)){assert.equal(step.jsonImageBytes,0);assert.equal(step.styleImageBytes,0);assert.equal(step.disabledWrites,1);assert.equal(step.created,6);assert.equal(step.host_preserved,true);assert.equal(step.other_method_preserved,true);}
});
test('four UI languages translate actual card nodes while preserving question, images and draw state',()=>{
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'assets/art-manifest.json'),'utf8')),art=Object.fromEntries(manifest.assets.map(asset=>[asset.key,{...asset,src:'/art/'+path.basename(asset.file||asset.path)}]));
  const e=setup({i18n:true,config:{art}});e.api.update('all',{question:'User question 原文を保つ 그대로'});finishCards(e,'tarot',3);finishCards(e,'lenormand',3);
  const state=plain(e.api.getState()),pool=e.find({system:'tarot'}).querySelector('.mx-draw-pool'),cards=pool.children.slice(),created=e.created(),random=e.calls(),bytes=e.metrics.imageSrcBytes;
  for(const language of ['en','ja','ko','zh-CN']){
    e.context.MingxueI18n.setLanguage(language);assert.deepEqual(plain(e.api.getState()),state);assert.deepEqual(pool.children,cards);assert.equal(e.created(),created);assert.equal(e.calls(),random);assert.equal(e.metrics.imageSrcBytes,bytes);assert.ok(e.host.textContent.includes('User question 原文を保つ 그대로'));
    for(let i=0;i<cards.length;i++){assert.equal(cards[i].querySelector('.mx-draw-card-name').textContent,e.context.MingxueI18n.t(state.methods.tarot.picked[i].name));if(language==='en')assert.doesNotMatch(cards[i].querySelector('.mx-draw-card-caption').textContent,/[\u3400-\u9fff]/);}
  }
});
test('shuffle uses rejection rather than biased modulo',()=>{
  const e=setup({queue:[0xffffffff,0],constant:0});e.api.update(['tarot'],{question:QUESTION});e.click('tarot','start');assert.equal(e.calls(),78);assert.equal(e.api.getState().methods.tarot.started,true);
});
test('a failing random source is bounded and preserves an earlier draw',()=>{
  const e=setup({constant:0xffffffff});e.api.update(['tarot'],{question:QUESTION});e.click('tarot','start');assert.equal(e.calls(),256);assert.equal(e.api.getState().methods.tarot.started,false);assert.match(e.host.textContent,/不会被盖掉/);
});
test('tarot cards are unique and orientation is the actual retained choice',()=>{
  for(let round=0;round<6;round++){
    const e=setup({real:true});e.api.update(['tarot'],{question:QUESTION});e.select('tarot','spread','celtic');finishCards(e,'tarot',10);
    const state=plain(e.api.getState().methods.tarot);assert.equal(state.picked.length,10);assert.equal(new Set(state.picked.map(card=>card.id)).size,10);
    assert.ok(state.picked.every(card=>['upright','reversed'].includes(card.orientation)));
    const before=e.calls();e.click('tarot','pick',0);assert.equal(e.calls(),before);assert.equal(e.api.getState().methods.tarot.picked.length,10);
    const request=base();request.method_options.tarot={seed:999,upright_only:true};const saved=plain(e.api.apply(request,['tarot']));
    assert.deepEqual(saved.method_options.tarot.cards,state.picked.map(card=>card.id+':'+card.orientation));assert.ok(!('seed'in saved.method_options.tarot));assert.ok(!('upright_only'in saved.method_options.tarot));
  }
});
test('upright-only control changes no random outcome after start',()=>{
  const e=setup();e.api.update(['tarot'],{question:QUESTION});const box=e.find({system:'tarot',control:'reversals'});box.checked=false;box.fire('change');finishCards(e,'tarot',3);
  assert.ok(e.api.getState().methods.tarot.picked.every(card=>card.orientation==='upright'));
});
test('every Lenormand size preserves all clicked positions in order',()=>{
  for(const [spread,count]of [['pair',2],['three',3],['nine',9],['grand',36]]){
    const e=setup({real:true});e.api.update(['lenormand'],{question:QUESTION});e.select('lenormand','spread',spread);if(spread==='grand')e.select('lenormand','layout','8x4+4');
    e.click('lenormand','start');const positions=Array.from({length:count},(_,i)=>35-i);for(const slot of positions)e.click('lenormand','pick',slot);
    const state=plain(e.api.getState().methods.lenormand),result=plain(e.api.apply(base(),['lenormand'])).method_options.lenormand;
    assert.equal(new Set(result.cards).size,count);assert.deepEqual(result.cards,state.picked.map(card=>card.number));assert.deepEqual(state.slots,positions);
    assert.equal(result.layout,spread==='grand'?'8x4+4':spread==='nine'?'3x3':'line');
  }
});
test('six gestures each toss three coins and preserve bottom-to-top values',()=>{
  const bits=[0,0,0,1,0,0,1,1,0,1,1,1,0,0,0,1,1,1];const e=setup({queue:bits});e.api.update(['iching','yilin'],{question:QUESTION});finishRows(e,'iching',6);
  const before=e.calls(),result=plain(e.api.apply(base(),['iching','yilin']));assert.equal(before,18);assert.equal(e.calls(),before);
  assert.deepEqual(result.method_options.iching.lines,[6,7,8,9,6,9]);assert.equal(result.method_options.iching.direction,'bottom-to-top');
  assert.equal(result.method_options.yilin.method,'lines');assert.deepEqual(result.method_options.yilin.lines,result.method_options.iching.lines);
});
test('Lingqi really tosses twelve binary faces including 0 and 4 boundaries',()=>{
  for(const [bit,expected]of [[0,[0,0,0]],[0xffffffff,[4,4,4]]]){
    const e=setup({constant:bit});e.api.update(['lingqijing'],{question:QUESTION});finishRows(e,'lingqijing',3);
    assert.equal(e.calls(),12);assert.deepEqual(plain(e.api.apply(base(),['lingqijing'])).method_options.lingqijing.counts,expected);
    assert.equal(e.api.getState().methods.lingqijing.rows.flat().length,12);
  }
});
test('geomancy has four top-to-bottom four-line mothers',()=>{
  const e=setup({queue:[0,1,0,1,1,1,1,1,0,0,0,0,1,0,1,0]});e.api.update(['geomancy'],{question:QUESTION});finishRows(e,'geomancy',4);
  assert.equal(e.calls(),16);assert.deepEqual(plain(e.api.apply(base(),['geomancy'])).method_options.geomancy.mothers,['2121','1111','2222','1212']);
});
test('started but incomplete is explicit; user skip clears without randomness',()=>{
  const e=setup();e.api.update(['tarot'],{question:QUESTION});e.click('tarot','start');e.click('tarot','pick',0);
  assert.throws(()=>e.api.apply(base(),['tarot']),error=>error.code==='unfinished_draw'&&!/权限|接口|输入|输出|payload|schema/i.test(error.message));
  const before=e.calls();e.click('tarot','skip');assert.equal(e.calls(),before);assert.deepEqual(plain(e.api.apply(base(),['tarot'])),base());
});
test('selection mode and question changes do not redraw or relabel the original question',()=>{
  const e=setup();e.api.update(['tarot'],{pair:false,question:QUESTION});finishCards(e,'tarot',3);const old=plain(e.api.getState().methods.tarot),before=e.calls();
  e.api.update([],{pair:true,question:'新的共同问题是什么？'});assert.equal(e.host.hidden,true);e.api.update(['tarot'],{pair:true,question:'新的共同问题是什么？'});
  assert.equal(e.calls(),before);assert.deepEqual(plain(e.api.getState().methods.tarot),old);assert.match(e.host.textContent,/仍保留/);
  const request=base(true);request.preferences.question='新的共同问题是什么？';const saved=plain(e.api.apply(request,['tarot']));
  assert.equal(saved.method_options.tarot.question,QUESTION);assert.match(saved.preferences.answers['本次亲手抽取说明'].join(''),/不是两次独立抽取/);assert.match(saved.preferences.answers['本次亲手抽取说明'].join(''),/后来问题或人数有变/);
  const beforeRestart=e.calls();e.click('tarot','start');assert.ok(e.calls()>beforeRestart);assert.equal(e.api.getState().methods.tarot.question,'新的共同问题是什么？');
});
test('advanced manual data and existing operation notes are never silently replaced',()=>{
  const e=setup({constant:0});e.api.update(['tarot'],{question:QUESTION});finishCards(e,'tarot',3);const request=base();request.method_options.tarot={spread:'single',cards:['major-00:upright']};const original=plain(request);
  assert.throws(()=>e.api.apply(request,['tarot']),error=>error.code==='manual_conflict');assert.deepEqual(request,original);
  const userNote=base();userNote.preferences.answers['本次亲手抽取说明']='用户自己写的说明';assert.throws(()=>e.api.apply(userNote,['tarot']),error=>error.code==='operation_note_conflict');assert.equal(userNote.preferences.answers['本次亲手抽取说明'],'用户自己写的说明');
});
test('answer capacity and original question chunks remain bounded',()=>{
  const e=setup({constant:0});e.api.update(['tarot'],{question:'我想把这一年的安排想清楚。'.repeat(200)});finishCards(e,'tarot',3);
  const request=base();for(let i=0;i<49;i++)request.preferences.answers['问题'+i]='回答';const result=plain(e.api.apply(request,['tarot']));
  assert.equal(Object.keys(result.preferences.answers).length,50);assert.ok(result.preferences.answers['本次亲手抽取说明'].every(text=>text.length<=2000));
  request.preferences.answers['最后一题']='回答';assert.throws(()=>e.api.apply(request,['tarot']),error=>error.code==='answer_capacity');
});
test('only a verified exact atlas mapping can depict the selected card',()=>{
  const art={card_back:{src:'/art/back.png'},tarot_major:{src:'/art/major.png',width:100,height:150,atlas:{cols:1,rows:1,index_mapping:{'major-01':0},verified_for_card_binding:false}}};
  const e=setup({constant:0,config:{art}});e.api.update(['tarot'],{question:QUESTION});e.click('tarot','start');assert.match(e.find({system:'tarot',action:'pick',slot:0}).parentElement.style['--mx-draw-back'],/\/art\/back/);e.click('tarot','pick',0);
  assert.equal(e.api.getState().methods.tarot.picked[0].id,'major-01');assert.equal(e.find({system:'tarot',action:'pick',slot:0}).children[0].style.backgroundImage,undefined);
  const before=e.calls();art.tarot_major.atlas.verified_for_card_binding=true;e.api.update(['tarot'],{question:QUESTION});assert.equal(e.calls(),before);assert.match(e.find({system:'tarot',action:'pick',slot:0}).children[0].children[0].src,/\/art\/major/);
});
test('real object-array mapping uses nonuniform pixel windows and rejects ambiguous matches',()=>{
  const art={tarot_major:{src:'/art/major.png',width:350,height:300,atlas:{cols:2,rows:1,verified_for_card_binding:true,
    index_mapping:[{index:0,name:'愚者',row:0,col:0},{index:1,name:'魔术师',row:0,col:1}],
    tiles:[{index:0,name:'愚者',x:0,y:0,width:190,height:300},{index:1,name:'魔术师',x:190,y:0,width:160,height:300}]}}};
  const e=setup({constant:0,config:{art}});e.api.update(['tarot'],{question:QUESTION});finishCards(e,'tarot',3);
  const binding=plain(e.api.getArtBinding('tarot','major-01'));assert.deepEqual(binding.box,{x:190,y:0,width:160,height:300});
  const picture=e.find({system:'tarot',action:'pick',slot:0}).children[0];assert.equal(picture.style.aspectRatio,'160 / 300');
  assert.equal(picture.style.border,'0');assert.equal(picture.children[0].style.width,'218.75%');assert.equal(picture.children[0].style.left,'-118.75%');
  art.tarot_major.atlas.tiles.push({...art.tarot_major.atlas.tiles[1],x:0,width:160});assert.equal(e.api.getArtBinding('tarot','major-01'),null);
  art.tarot_major.atlas.tiles.pop();art.tarot_major.atlas.tiles[0].x=190;art.tarot_major.atlas.tiles[0].width=160;assert.equal(e.api.getArtBinding('tarot','major-01'),null);
});
test('unverified or suit-only illustration cannot stand in for fourteen minor cards',()=>{
  const art={tarot_suits:{src:'/art/four-suits.png',width:200,height:200,atlas:{cols:2,rows:2,verified_for_card_binding:true,index_mapping:[{name:'星币三',card_id:'pentacles-03',index:3}]}}};
  const e=setup({config:{art}});assert.equal(e.api.getArtBinding('tarot','pentacles-03'),null);
  art.tarot_pentacles={src:'/art/pentacles.png',width:200,height:300,atlas:{cols:1,rows:1,verified_for_card_binding:false,index_mapping:[{index:0,name:'星币三',card_id:'pentacles-03'}]}};
  assert.equal(e.api.getArtBinding('tarot','pentacles-03'),null);art.tarot_pentacles.atlas.verified_for_card_binding=true;
  assert.equal(e.api.getArtBinding('tarot','pentacles-03').key,'tarot_pentacles');
});
let actualArtBindings=[];
test('the actual manifest binds all 78 plus 36 cards to distinct verified picture windows',()=>{
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'assets/art-manifest.json'),'utf8'));
  const art=Object.fromEntries(manifest.assets.map(asset=>[asset.key,{...asset,src:'/art/'+path.basename(asset.file||asset.path)}]));
  const e=setup({config:{art}}),catalog=e.api.getCatalog(),seen=new Set();
  for(const [system,cards]of [['tarot',catalog.tarot],['lenormand',catalog.lenormand]])for(const card of cards){
    const binding=plain(e.api.getArtBinding(system,card.id));assert.ok(binding,'missing exact verified image for '+card.id);
    const signature=binding.src+'|'+JSON.stringify(binding.box);assert.ok(!seen.has(signature),'image window reused: '+card.id);seen.add(signature);
    assert.ok(fs.existsSync(path.join(root,'assets/art',path.basename(binding.src))));actualArtBindings.push({system,card_id:card.id,...binding});
  }
  assert.equal(seen.size,114);assert.equal(e.api.getArtBinding('tarot','major-18').key,'tarot_major');
  assert.equal(e.api.getArtBinding('tarot','pentacles-03').key,'tarot_pentacles');assert.equal(e.api.getArtBinding('tarot','swords-07').key,'tarot_swords');
  assert.equal(e.calls(),0);
});
test('question and card text are DOM text rather than executable markup',()=>{
  const e=setup({constant:0});e.api.update(['tarot'],{question:'<img src=x onerror=alert(1)> 我该怎么安排？'});finishCards(e,'tarot',3);
  assert.match(e.host.textContent,/<img src=x/);assert.equal(e.nodes().some(node=>node.tagName==='img'),false);assert.doesNotMatch(source,/innerHTML\s*=/);
});

// Functional handoff samples are produced only through the same clicked UI.
const all=setup({real:true});all.api.update('all',{pair:true,question:QUESTION});finishCards(all,'tarot',3);all.select('lenormand','spread','grand');finishCards(all,'lenormand',36);finishRows(all,'iching',6);finishRows(all,'lingqijing',3);finishRows(all,'geomancy',4);
const before=all.calls(),pairRequest=plain(all.api.apply(base(true),'all'));assert.equal(all.calls(),before);
const singleRequest=plain(all.api.apply(base(false),'all'));assert.equal(all.calls(),before);
process.stdout.write(JSON.stringify({passed,catalog:plain(all.api.getCatalog()),requests:{pair:pairRequest,single:singleRequest},state:plain(all.api.getState()),artBindings:actualArtBindings}));
