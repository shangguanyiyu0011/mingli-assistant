'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto,createHash}=require('node:crypto');
const root=process.env.MINGXUE_TEST_SKILL_ROOT||path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'ui/intake.js'),'utf8');
function setup(options={}){
  const nodes=new Map(),radios={mode:'single','systems-mode':'all'},calls=[],revoked=[],urls=[],draws={init:0,update:0};
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',maxLength:2000,checked:false,hidden:false,disabled:false,type:'text',dataset:{},listeners:{},firstChild:{textContent:''},classList:{toggle(){}},querySelectorAll(){return [];},addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},async fire(type,event={}){for(const fn of this.listeners[type]||[])await fn({target:this,preventDefault(){},...event});},dispatchEvent(event){this.fire(event.type);return true;},focus(){this.focused=true;},matches(selector){return selector.split(',').includes('#'+this.id);},scrollIntoView(){}});return nodes.get(id);};
  for(const p of ['a','b']){node(p+'-calendar').value='solar';node(p+'-time-kind').value='unknown';}
  node('cast-when').value='now';
  const document={getElementById:node,querySelector(query){if(query.includes('workbench-token'))return {content:'synthetic-test-token'};if(query.includes('mingli-intake-mode'))return {content:'agent'};const match=/name=["']?([\w-]+)/.exec(query);return match?{value:radios[match[1]]}:null;},querySelectorAll(){return [];}};
  class FileReader{readAsDataURL(file){Promise.resolve().then(()=>{if(file.readError){this.onerror();return;}this.result='data:'+file.type+';base64,c3ludGhldGlj';this.onload();});}}
  class TestURL extends URL{static createObjectURL(file){const url='blob:synthetic-'+urls.length;urls.push({url,file});return url;}static revokeObjectURL(url){revoked.push(url);}}
  const response=data=>({ok:true,json:async()=>data});
  let nextPhoto=0;
  const context={document,URL:TestURL,URLSearchParams,Event,location:{hash:'',href:'http://127.0.0.1:1/',pathname:'/',search:''},history:{replaceState(){}},sessionStorage:{getItem(){return '';},setItem(){}},MingxueDraws:{init(){draws.init++;},update(){draws.update++;},apply(value){return value;}},async fetch(url,request){if(url==='/api/catalog')return response({systems:[]});const body=request.body===undefined?undefined:JSON.parse(request.body);calls.push({url,body,headers:request.headers});if(options.handler)return options.handler(url,body,response);if(url==='/api/photos'){const id=String(++nextPhoto).padStart(32,'0');return response({ref:{id,kind:body.kind,sha256:'b'.repeat(64)}});}return response({status:'removed'});},addEventListener(){},FileReader,console,Date,MINGXUE_OFFLINE:!!options.offline,crypto:options.crypto?webcrypto:undefined};
  context.window=context;
  if(options.i18n){context.MINGXUE_LOCALES=JSON.parse(fs.readFileSync(path.join(root,'ui/intake-locales.json'),'utf8'));vm.runInNewContext(fs.readFileSync(path.join(root,'ui/i18n.js'),'utf8'),context);context.MingxueI18n.setLanguage(options.language||'zh-CN');}
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'window.testIntake={collect,namingFor,update,photos,uploadPhoto,removePhoto,wellbeingTopics,wellbeingQuestions,switchWellbeing};})();'),context);
  node('a-name').value='合成测试';node('a-date').value='2000-08-16';node('a-birthplace').value='深圳市，广东省';
  for(const p of ['a','b']){node(p+'-wellbeing-topic').value='overview';node(p+'-wellbeing-current').textContent='当前：综合了解';}
  return {node,radios,api:context.testIntake,calls,revoked,urls,draws,context,i18n:context.MingxueI18n};
}
const plain=value=>JSON.parse(JSON.stringify(value)),tests=[];
const test=(name,fn)=>tests.push([name,fn]);
const photoFile=(extra={})=>({name:'synthetic.png',type:'image/png',size:40,...extra});
test('only one form and clear time/photo choices',()=>{
  const html=fs.readFileSync(path.join(root,'ui/intake.html'),'utf8');
  assert.doesNotMatch(html+source,/fill-mode|data-fill-detail|基础填写|详细填写/);
  assert.match(source,/palm_left/);assert.match(source,/palm_right/);assert.match(source,/portrait/);assert.match(source,/跨午夜/);
});
const presetIds=[...fs.readFileSync(path.join(root,'ui/intake.html'),'utf8').matchAll(/<button type="button" data-question-preset="([^"]+)" aria-controls="question">([^<]+)<\/button>/g)];
const clickPreset=(e,id)=>{const target={dataset:{questionPreset:id},closest(){return this;}};return e.node('question-presets').fire('click',{target});};
test('sixteen distinct accessible presets add natural editable questions',async()=>{
  assert.equal(presetIds.length,16);assert.equal(new Set(presetIds.map(x=>x[1])).size,16);assert.equal(new Set(presetIds.map(x=>x[2])).size,16);
  for(const [,id]of presetIds){const e=setup();await clickPreset(e,id);assert.ok(e.node('question').value.length>35);assert.match(e.node('question').value,/[？。]/);assert.equal(e.node('question-place').hidden,false);assert.equal(e.node('question').focused,true);assert.equal(e.draws.init,0);e.node('question').value+='这是我自己的补充。';assert.match(e.node('question').value,/自己的补充/);}
});
test('preset appends without overwriting or duplication and respects question capacity',async()=>{
  const e=setup();e.node('question').value='用户原来写的内容。';await clickPreset(e,'career');const once=e.node('question').value;assert.ok(once.startsWith('用户原来写的内容。\n\n'));await clickPreset(e,'career');assert.equal(e.node('question').value,once);await clickPreset(e,'learning');assert.ok(e.node('question').value.startsWith(once));
  e.node('question').value='保'.repeat(1999);await clickPreset(e,'parenting');assert.equal(e.node('question').value,'保'.repeat(1999));assert.match(e.node('question-preset-feedback').textContent,/快写满/);assert.equal(e.calls.length,0);
});
test('presets preserve unknown personal circumstances and brand/footer are removed',()=>{
  const html=fs.readFileSync(path.join(root,'ui/intake.html'),'utf8');assert.doesNotMatch(html,/<header\b|class="brand"|<footer\b|从你知道的资料开始/);assert.match(html,/id="submit"/);assert.match(html,/id="cancel"/);
  assert.match(source,/如果处于单身/);assert.match(source,/如果正在恋爱/);assert.match(source,/不假定我已经有孩子/);assert.match(source,/如果考虑换工作/);
  const css=fs.readFileSync(path.join(root,'ui/intake.css'),'utf8');assert.match(css,/\.question-presets\{[^}]*repeat\(4/);assert.match(css,/@media\(max-width:560px\)\{\.question-presets\{[^}]*repeat\(2/);
});
const wellbeingIds=['mood','stress','support','focus','pace','decisions','resources','changes','clarify','start'];
const wellbeingPair=(options={})=>{const e=setup(options);e.radios.mode='pair';e.node('b-name').value='合成乙';e.node('b-date').value='1995-03-21';e.node('b-birthplace').value='Berlin, Germany';e.node('relationship').value='friend';return e;};
const clearWellbeing=(e,p)=>e.node('intake').fire('click',{target:{dataset:{clearWellbeing:p},closest(selector){return selector==='[data-clear-wellbeing]'?this:null;}}});
const selectWellbeing=(e,topic,p='a')=>{const target=e.node(p+'-wellbeing-topic');target.dataset.wellbeingTopic=p;target.value=topic;return e.node('intake').fire('change',{target});};
let wellbeingMatrix=[];
test('optional wellbeing starts empty and never adds unanswered or scored data',()=>{
  const e=setup();assert.equal(e.api.collect().people[0].person.notes,undefined);for(const id of wellbeingIds)assert.equal(e.node('a-wellbeing-'+id).value,'');
  e.node('a-notes').value='原来的个人说明。';assert.equal(e.api.collect().people[0].person.notes,'原来的个人说明。');assert.deepEqual(plain(e.api.collect().preferences.answers),{});
  const group=source.slice(source.indexOf('<details class="details wellbeing">'),source.indexOf('关于这个人，还有想补充的吗？'));assert.match(group,/心理与近况（选填）/);assert.doesNotMatch(group,/<details[^>]*\bopen|\bselected\b|\brequired\b/);assert.match(e.node('people').innerHTML,/<option value="">暂不选择<\/option>/);assert.match(group,/type="button"[^>]*data-clear-wellbeing/);
});
test('wellbeing choices append readable self reports without replacing any original notes or background',()=>{
  const e=setup(),questions=e.api.wellbeingQuestions(),values=questions.map(row=>row[2][0]);
  questions.forEach(([id],i)=>e.node('a-wellbeing-'+id).value=values[i]);e.node('a-notes').value='我原来的补充。';e.node('answer-background').value='用户填写的事情背景';e.node('answer-uncertainty').value='用户填写的不确定说明';
  const data=plain(e.api.collect());assert.ok(data.people[0].person.notes.startsWith('我原来的补充。\n\n本人自述（心理与近况｜综合了解）\n'));for(const value of values)assert.ok(data.people[0].person.notes.includes(value));
  assert.deepEqual(data.preferences.answers,{'事情背景':'用户填写的事情背景','补充或不确定说明':'用户填写的不确定说明'});assert.equal(data.people[0].questionnaire,undefined);assert.ok(data.people[0].person.notes.length<4000);assert.doesNotMatch(data.people[0].person.notes,/wellbeing|mood|stress|得分|分数|人格类型/);
  e.node('a-wellbeing-mood').value='不支持的选项';assert.throws(()=>e.api.collect(),/重新选择心理与近况/);
});
test('wellbeing is owned by each person; single submission excludes retained B selections',()=>{
  const e=wellbeingPair();e.node('a-wellbeing-stress').value='独处整理';e.node('b-wellbeing-support').value='被理解';e.node('b-notes').value='乙自己的说明';const pair=plain(e.api.collect());
  assert.match(pair.people[0].person.notes,/独处整理/);assert.doesNotMatch(pair.people[0].person.notes,/被理解|乙自己的说明/);assert.match(pair.people[1].person.notes,/被理解/);assert.doesNotMatch(pair.people[1].person.notes,/独处整理/);
  e.radios.mode='single';e.api.update();const single=plain(e.api.collect());assert.equal(single.people.length,1);assert.doesNotMatch(JSON.stringify(single),/被理解|乙自己的说明/);assert.equal(e.node('b-wellbeing-support').value,'被理解');
  e.radios.mode='pair';e.api.update();assert.deepEqual(plain(e.api.collect()),pair);
});
test('wellbeing clearing changes only that persons current choices and does not redraw interactive cards',async()=>{
  const e=wellbeingPair();e.node('draw-options').open=true;await e.node('draw-options').fire('toggle');await new Promise(resolve=>setImmediate(resolve));const before={...e.draws},markup=e.node('people').innerHTML;e.node('a-notes').value='保留我的说明';e.node('b-wellbeing-mood').value='有些疲惫';
  for(const [id,value]of [['mood','忙碌充实'],['stress','找人聊聊']]){e.node('a-wellbeing-'+id).value=value;await e.node('intake').fire('change',{target:e.node('a-wellbeing-'+id)});}
  await clearWellbeing(e,'a');for(const id of wellbeingIds)assert.equal(e.node('a-wellbeing-'+id).value,'');assert.equal(e.node('b-wellbeing-mood').value,'有些疲惫');assert.equal(e.api.collect().people[0].person.notes,'保留我的说明');assert.equal(e.node('a-notes').value,'保留我的说明');assert.deepEqual(e.draws,before);assert.equal(e.node('people').innerHTML,markup);assert.equal(e.calls.length,0);assert.match(e.node('a-wellbeing-feedback').textContent,/已清除/);
  for(const topic of Object.keys(e.api.wellbeingTopics))await selectWellbeing(e,topic);assert.deepEqual(e.draws,before);assert.equal(e.node('people').innerHTML,markup);
});
test('all sixteen topics have ten distinct bounded questions with seven theme-specific questions',()=>{
  const e=setup(),topics=e.api.wellbeingTopics;assert.equal(Object.keys(topics).length,16);assert.deepEqual(Object.keys(topics),presetIds.map(row=>row[1]));const distinctive=new Set();
  for(const [topic,[label,rows]]of Object.entries(topics)){
    const questions=plain(e.api.wellbeingQuestions(topic));assert.equal(questions.length,10);assert.equal(new Set(questions.map(row=>row[0])).size,10);assert.equal(new Set(questions.map(row=>row[1])).size,10);assert.equal(rows.length,7);assert.ok(label.length<10);
    for(const [id,text,options]of questions){assert.ok(!['topic','current','fields','feedback'].includes(id));assert.ok(text.length<=30);assert.equal(options.length,4);assert.equal(new Set(options).size,4);assert.ok(options.every(value=>value.length<=20));}
    for(const [,text]of rows){assert.ok(!distinctive.has(text),'duplicated topic-specific question: '+text);distinctive.add(text);}
  }
  assert.equal(distinctive.size,112);
});
test('topic switching restores separate A/B drafts and exports only current topic',async()=>{
  const e=wellbeingPair();e.node('a-wellbeing-mood').value='忙碌充实';e.node('b-wellbeing-mood').value='有些疲惫';
  await selectWellbeing(e,'career');assert.equal(e.node('a-wellbeing-mood').value,'');assert.equal(e.node('b-wellbeing-mood').value,'');e.node('a-wellbeing-work').value='分析解决问题';e.node('b-wellbeing-work').value='表达创作';
  const career=plain(e.api.collect());assert.match(career.people[0].person.notes,/职业方向/);assert.match(career.people[0].person.notes,/分析解决问题/);assert.doesNotMatch(career.people[0].person.notes,/忙碌充实|有些疲惫|表达创作/);
  await selectWellbeing(e,'overview','b');assert.equal(e.node('a-wellbeing-mood').value,'忙碌充实');assert.equal(e.node('b-wellbeing-mood').value,'有些疲惫');await clearWellbeing(e,'a');assert.equal(e.api.collect().people[0].person.notes,undefined);
  await selectWellbeing(e,'career');assert.equal(e.node('a-wellbeing-work').value,'分析解决问题');assert.equal(e.node('b-wellbeing-work').value,'表达创作');assert.deepEqual(plain(e.api.collect()),career);
  e.radios.mode='single';e.api.update();assert.doesNotMatch(JSON.stringify(e.api.collect()),/表达创作|有些疲惫/);e.radios.mode='pair';e.api.update();assert.deepEqual(plain(e.api.collect()),career);
});
test('each preset links its topic without overwriting questions, notes, or drawing cards',async()=>{
  const e=setup();e.node('draw-options').open=true;await e.node('draw-options').fire('toggle');await new Promise(resolve=>setImmediate(resolve));const markup=e.node('people').innerHTML,initial=e.draws.init;e.node('a-notes').value='原始补充不动';
  for(const [,topic,label]of presetIds){const old=e.node('question').value;await clickPreset(e,topic);assert.ok(e.node('question').value.startsWith(old));assert.equal(e.node('a-wellbeing-topic').value,topic);assert.equal(e.node('b-wellbeing-topic').value,topic);assert.equal(e.node('a-wellbeing-current').textContent,'当前：'+label);assert.equal(e.node('people').innerHTML,markup);assert.equal(e.node('a-notes').value,'原始补充不动');assert.equal(e.draws.init,initial);}
});
test('all sixteen topic drafts collect independently with optional name paths and unknown birth times',async()=>{
  const e=wellbeingPair(),topics=Object.keys(e.api.wellbeingTopics),saved=new Map();e.node('a-notes').value='甲的原有补充。'.repeat(200);e.node('b-notes').value='乙的原有补充。';
  for(let i=0;i<topics.length;i++){
    const topic=topics[i];await selectWellbeing(e,topic);const questions=e.api.wellbeingQuestions();assert.equal(questions.length,10);for(const [id]of questions){assert.equal(e.node('a-wellbeing-'+id).value,'');assert.equal(e.node('b-wellbeing-'+id).value,'');}
    if(i%4===0){e.node('a-name').value='欧阳若水';e.node('a-analyze-name').checked=true;e.node('a-surname-confirm').value='';}
    else if(i%4===1){e.node('a-name').value='王张三四';e.node('a-analyze-name').checked=true;e.node('a-surname-confirm').value='王张';}
    else{e.node('a-name').value=i%4===2?'昵称-Sample':'合成称呼';e.node('a-analyze-name').checked=false;e.node('a-surname-confirm').value='';}
    for(const [id,,options]of questions){e.node('a-wellbeing-'+id).value=options[0];e.node('b-wellbeing-'+id).value=options[3];}
    const pair=plain(e.api.collect());assert.ok(pair.people.every(p=>p.birth.time===null&&p.person.notes.length<=4000));assert.match(pair.people[0].person.notes,new RegExp('心理与近况｜'+e.api.wellbeingTopics[topic][0]));assert.equal(pair.people[0].person.notes.split('\n').length,13);assert.ok(pair.people[0].person.notes.startsWith(e.node('a-notes').value));
    if(i%4===0)assert.deepEqual(pair.people[0].name,{surname:'欧阳',given:'若水'});else if(i%4===1)assert.deepEqual(pair.people[0].name,{surname:'王张',given:'三四'});else assert.equal(pair.people[0].name,undefined);
    saved.set(topic,questions.map(([id])=>[id,e.node('a-wellbeing-'+id).value,e.node('b-wellbeing-'+id).value]));wellbeingMatrix.push({topic,mode:'pair',request:pair});e.radios.mode='single';e.api.update();const single=plain(e.api.collect());assert.equal(single.people.length,1);assert.doesNotMatch(JSON.stringify(single),/乙的原有补充/);wellbeingMatrix.push({topic,mode:'single',request:single});e.radios.mode='pair';e.api.update();
  }
  for(const topic of topics){await selectWellbeing(e,topic);for(const [id,a,b]of saved.get(topic)){assert.equal(e.node('a-wellbeing-'+id).value,a);assert.equal(e.node('b-wellbeing-'+id).value,b);}}
});
test('unknown time and unresolved place remain facts',()=>{const e=setup(),r=plain(e.api.collect());assert.equal(r.people[0].birth.time,null);assert.equal(r.people[0].birth.shichen,undefined);assert.equal(r.people[0].birthplace,'深圳市，广东省');assert.equal(r.people[0].birth.timezone,undefined);assert.equal(r.people[0].location,undefined);assert.equal(r.people[0].name,undefined);assert.equal(r.preferences.depth,'detailed');assert.equal(r.preferences.cast,undefined);});
test('compound surname is retained without invented strokes',()=>{const e=setup();e.node('a-name').value='欧阳若水';e.node('a-analyze-name').checked=true;assert.deepEqual(plain(e.api.collect()).people[0].name,{surname:'欧阳',given:'若水'});assert.equal(e.api.collect().people[0].name.strokes,undefined);});
test('name correction and consent remain optional',()=>{const e=setup();e.node('a-name').value='王张三四';e.node('a-analyze-name').checked=true;assert.throws(()=>e.api.collect(),/确认.*姓氏/);e.node('a-surname-confirm').value='王张';assert.deepEqual(plain(e.api.collect()).people[0].name,{surname:'王张',given:'三四'});e.node('a-name').value='Happy';assert.throws(()=>e.api.collect(),/真实姓名/);e.node('a-analyze-name').checked=false;assert.equal(e.api.collect().people[0].name,undefined);});
test('all twelve periods retain null time and switches never carry stale precision',()=>{
  const e=setup();e.node('a-time-kind').value='exact';assert.throws(()=>e.api.collect(),/具体出生时间/);e.node('a-time').value='24:00';assert.throws(()=>e.api.collect(),/具体出生时间/);e.node('a-time').value='19:23';assert.equal(e.api.collect().people[0].birth.time,'19:23');
  e.node('a-time-kind').value='shichen';assert.throws(()=>e.api.collect(),/知道的时辰/);
  for(const value of '子丑寅卯辰巳午未申酉戌亥'){e.node('a-shichen').value=value;const birth=e.api.collect().people[0].birth;assert.equal(birth.time,null);assert.equal(birth.shichen,value);}
  e.node('a-shichen').value='23:00';assert.throws(()=>e.api.collect(),/知道的时辰/);e.node('a-shichen').value='子';e.node('a-time-kind').value='unknown';assert.deepEqual(plain(e.api.collect().people[0].birth),{date:'2000-08-16',calendar:'solar',time:null});e.node('a-time-kind').value='exact';assert.equal(e.api.collect().people[0].birth.shichen,undefined);
});
test('pair changes preserve B photos and exclude B from single submission',async()=>{
  const e=setup();e.node('answer-background').value='目前在考虑换工作';e.api.photos.a.push({ref:{id:'a'.repeat(32),kind:'palm_left',sha256:'b'.repeat(64),include_in_report:false}});e.api.photos.b.push({ref:{id:'c'.repeat(32),kind:'portrait',sha256:'d'.repeat(64),include_in_report:false}});
  e.radios.mode='pair';e.node('b-name').value='合成乙';e.node('b-date').value='1995-03-21';e.node('b-birthplace').value='Berlin, Germany';e.node('relationship').value='friend';const before=plain(e.api.collect());
  for(const mode of ['single','pair']){e.radios.mode=mode;await e.node('intake').fire('change',{target:{name:'mode',value:mode,dataset:{}}});if(mode==='single'){assert.equal(e.api.collect().people.length,1);assert.equal(e.api.photos.b.length,1);}}
  assert.deepEqual(plain(e.api.collect()),before);assert.equal(e.calls.length,0);
});
test('question place and actual submission clock are required only for questions',()=>{const e=setup();e.node('question').value='合成测试问题';assert.throws(()=>e.api.collect(),/所在的城市/);e.node('cast-same-birthplace').checked=true;const r=plain(e.api.collect());assert.equal(r.preferences.cast_place,'深圳市，广东省');assert.match(r.preferences.cast.datetime_utc,/Z$/);assert.equal(r.preferences.cast.timezone,undefined);e.node('cast-when').value='past';assert.throws(()=>e.api.collect(),/当时的日期/);e.node('cast-datetime').value='2026-07-01T08:30';assert.deepEqual(plain(e.api.collect()).preferences.cast,{date:'2026-07-01',time:'08:30'});});
test('draws initialize only when opened; typing never initializes them',async()=>{const e=setup();assert.equal(e.draws.init,0);e.node('question').value='合成问题';await e.node('question').fire('input');assert.equal(e.draws.update,0);e.node('draw-options').open=true;await e.node('draw-options').fire('toggle');assert.equal(e.draws.init,1);await e.node('draw-options').fire('toggle');assert.equal(e.draws.init,1);});
test('selections queue and use local previews in both modes',async()=>{for(const offline of [false,true]){const e=setup({offline}),input=e.node('a-photo-palm_left');input.value='synthetic.png';const first=e.api.uploadPhoto('a',photoFile({type:''}),'palm_left',input),second=e.api.uploadPhoto('a',photoFile({name:'right.jpg',type:'image/jpeg'}),'palm_right',e.node('a-photo-palm_right'));assert.equal(input.value,'');await Promise.all([first,second]);assert.equal(e.api.photos.a.length,2);assert.deepEqual(e.calls.map(x=>x.body.kind),['palm_left','palm_right']);assert.equal(e.calls[0].body.mime,'image/png');assert.match(e.node('a-photo-list').innerHTML,/blob:synthetic-0/);assert.equal(e.revoked.length,0);}});
test('read/upload failure preserves earlier photos and allows identical file reselection',async()=>{
  let attempts=0;const e=setup({handler(url,body,response){if(++attempts===1)throw Error('图片暂时无法保存。');return response({ref:{id:'a'.repeat(32),kind:body.kind,sha256:'b'.repeat(64)}});}}),input=e.node('a-photo-portrait');
  await e.api.uploadPhoto('a',photoFile(),'portrait',input);assert.equal(e.api.photos.a.length,0);assert.deepEqual(e.revoked,['blob:synthetic-0']);input.value='synthetic.png';await e.api.uploadPhoto('a',photoFile(),'portrait',input);assert.equal(input.value,'');assert.equal(e.api.photos.a.length,1);const kept=e.api.photos.a[0].url;
  await e.api.uploadPhoto('a',photoFile({readError:true}),'portrait',input);assert.equal(e.api.photos.a.length,1);assert.ok(!e.revoked.includes(kept));assert.match(e.node('a-photo-feedback').textContent,/重新选择/);
});
test('invalid and oversized selections reset and do not block recovery',async()=>{const e=setup(),input=e.node('a-photo-portrait');for(const file of [photoFile({type:'image/gif'}),photoFile({size:6*1024*1024+1})]){input.value='bad';await e.api.uploadPhoto('a',file,'portrait',input);assert.equal(input.value,'');}assert.equal(e.calls.length,0);await e.api.uploadPhoto('a',photoFile(),'portrait',input);assert.equal(e.api.photos.a.length,1);});
test('delete only changes state and revokes preview after confirmed success',async()=>{
  let fail=true;const e=setup({handler(url,body,response){if(url==='/api/photos')return response({ref:{id:'a'.repeat(32),kind:body.kind,sha256:'b'.repeat(64)}});if(fail)throw Error('暂时无法删除。');return response({status:'removed'});}});
  await e.api.uploadPhoto('a',photoFile(),'portrait',e.node('a-photo-portrait'));const url=e.api.photos.a[0].url;await assert.rejects(e.api.removePhoto('a',0));assert.equal(e.api.photos.a.length,1);assert.ok(!e.revoked.includes(url));fail=false;await e.api.removePhoto('a',0);assert.equal(e.api.photos.a.length,0);assert.ok(e.revoked.includes(url));
});
test('a saved upload with lost response is recovered by exact hash, owner and kind',async()=>{
  const bytes=Buffer.from('synthetic'),sha256=createHash('sha256').update(bytes).digest('hex'),id='a'.repeat(32);let post=0;
  const e=setup({crypto:true,handler(url,body,response){if(body){post++;throw Error('连接暂时中断。');}return response({photos:[{id,person:'B',kind:'portrait',sha256},{id:'c'.repeat(32),person:'A',kind:'palm_left',sha256},{id,person:'A',kind:'portrait',sha256}]});}});
  await e.api.uploadPhoto('a',photoFile({arrayBuffer:async()=>bytes}),'portrait',e.node('a-photo-portrait'));
  assert.equal(post,1);assert.equal(e.api.photos.a.length,1);assert.equal(e.api.photos.a[0].ref.id,id);assert.equal(e.calls[1].body,undefined);assert.match(e.calls[1].headers.Authorization,/Bearer/);assert.equal(e.revoked.length,0);
});
test('a lost deletion response is confirmed through the authenticated photo list',async()=>{
  const e=setup({handler(url,body,response){if(url==='/api/photos'&&body)return response({ref:{id:'a'.repeat(32),kind:body.kind,sha256:'b'.repeat(64)}});if(url.endsWith('/remove'))throw Error('连接暂时中断。');return response({photos:[]});}});
  await e.api.uploadPhoto('a',photoFile(),'portrait',e.node('a-photo-portrait'));await e.api.removePhoto('a',0);assert.equal(e.api.photos.a.length,0);assert.equal(e.revoked.length,1);
});
async function runTests(){let passed=0;for(const [name,fn]of tests){try{await fn();passed++;}catch(error){throw Error(name+': '+error.stack);}}const sample=wellbeingPair();sample.node('a-wellbeing-stress').value='独处整理';sample.node('b-wellbeing-support').value='被理解';sample.node('a-notes').value='甲自己的说明';sample.node('b-notes').value='乙自己的说明';const wellbeingRequest=plain(sample.api.collect());sample.radios.mode='single';sample.api.update();console.log(JSON.stringify({passed,wellbeingRequest,wellbeingSingleRequest:plain(sample.api.collect()),wellbeingMatrix}));}
if(require.main===module)runTests().catch(error=>{console.error(error);process.exitCode=1;});else module.exports={setup,wellbeingPair,selectWellbeing,clickPreset,presetIds,clearWellbeing,plain};
