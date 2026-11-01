'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {setup,wellbeingPair,selectWellbeing,clickPreset,presetIds,plain}=require('./test_intake_form.js');
const root=process.env.MINGXUE_TEST_SKILL_ROOT||path.resolve(__dirname,'..'),dictionary=JSON.parse(fs.readFileSync(path.join(root,'ui/intake-locales.json'),'utf8'));
const runtime=fs.readFileSync(path.join(root,'ui/i18n.js'),'utf8'),locales=['zh-CN','en','ja','ko'];let passed=0;const requests=[];
function test(name,fn){return Promise.resolve().then(fn).then(()=>{passed++;},error=>{throw Error(name+': '+error.stack);});}
class Text{constructor(value,parent){this.nodeType=3;this.data=value;this.parentElement=parent;}get textContent(){return this.data;}}
class Element{
  constructor(tag,attributes={}){this.nodeType=1;this.tagName=tag;this.attributes=attributes;this.childNodes=[];this.parentElement=null;this.value=attributes.value||'';}
  appendChild(child){child.parentElement=this;this.childNodes.push(child);return child;}
  getAttribute(key){return Object.prototype.hasOwnProperty.call(this.attributes,key)?this.attributes[key]:null;}
  setAttribute(key,value){this.attributes[key]=String(value);}
  get textContent(){return this.childNodes.map(child=>child.textContent).join('');}
  set textContent(value){this.childNodes=[new Text(String(value),this)];}
  matches(selector){return selector.split(',').some(item=>{item=item.trim();return item==='[data-i18n-ignore]'?this.getAttribute('data-i18n-ignore')!==null:item.startsWith('.')?(this.attributes.class||'').split(' ').includes(item.slice(1)):this.tagName===item;});}
  closest(selector){for(let node=this;node;node=node.parentElement){if(node.matches(selector))return node;if(selector.includes('.photo-item span')&&node.tagName==='span'&&node.parentElement?.closest('.photo-item'))return node;if(selector.includes('.name-review .hint')&&node.matches('.hint')&&node.parentElement?.closest('.name-review'))return node;}return null;}
}
const decode=value=>value.replace(/&(?:amp|lt|gt|quot|#39);/g,entity=>({'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"}[entity]));
function parse(markup){const body=new Element('body'),stack=[body],ids=new Map(),controls=[];
  for(const match of markup.matchAll(/<!--[\s\S]*?-->|<\/?[^>]+>|[^<]+/g)){
    const token=match[0];if(token.startsWith('<!--')||token.startsWith('<!'))continue;
    if(token.startsWith('</')){const tag=token.slice(2,-1).trim();while(stack.length>1){const closed=stack.pop();if(closed.tagName==='select'){const options=closed.childNodes.filter(node=>node.tagName==='option');closed.value=(options.find(node=>node.getAttribute('selected')!==null)||options[0])?.value||'';}if(closed.tagName===tag)break;}continue;}
    if(token.startsWith('<')){const tag=/^<([\w-]+)/.exec(token)?.[1];if(!tag)continue;const attrs={};for(const m of token.slice(tag.length+1,-1).matchAll(/([\w-]+)(?:="([^"]*)"|='([^']*)')?/g))attrs[m[1]]=decode(m[2]??m[3]??'');const node=stack.at(-1).appendChild(new Element(tag,attrs));if(attrs.id)ids.set(attrs.id,node);if(['input','select','textarea','button'].includes(tag))controls.push(node);if(!['input','meta','link','img','br','hr'].includes(tag))stack.push(node);}
    else stack.at(-1).appendChild(new Text(decode(token),stack.at(-1)));
  }return {body,ids,controls};
}
(async()=>{
  await test('all dictionaries contain complete quiz, presets and name text',()=>{
    const e=setup();for(const language of locales.slice(1)){assert.ok(dictionary[language]);for(const [topic]of presetIds.map(row=>[row[1]])){for(const [,label,options]of e.api.wellbeingQuestions(topic))for(const source of [label,...options]){assert.ok(Object.prototype.hasOwnProperty.call(dictionary[language],source),language+' missing '+source);assert.ok(dictionary[language][source].trim());}}}
  });
  await test('actual HTML and generated fields translate without replacing controls or values',()=>{
    const e=setup(),markup=fs.readFileSync(path.join(root,'ui/intake.html'),'utf8')+e.node('people').innerHTML;
    const dom=parse(markup),document={body:dom.body,documentElement:{},title:'综合命理 · 填写资料',getElementById:()=>null},context={document,MINGXUE_LOCALES:dictionary};context.window=context;vm.runInNewContext(runtime,context);
    const refs=dom.controls.slice();dom.ids.get('a-name').value='Free 原文 / そのまま';dom.ids.get('question').value='我的自由问题 must stay unchanged';const values=refs.map(node=>node.value);
    for(const language of locales){context.MingxueI18n.setLanguage(language);assert.deepEqual(dom.controls,refs);assert.deepEqual(refs.map(node=>node.value),values);assert.equal(dom.ids.get('a-name').value,'Free 原文 / そのまま');assert.equal(document.documentElement.lang,language);const expected=language==='zh-CN'?'出生日期':dictionary[language]['出生日期'];assert.ok(dom.body.textContent.includes(expected));assert.equal(dom.ids.get('a-name').getAttribute('placeholder'),language==='zh-CN'?'真实姓名或你喜欢的称呼':dictionary[language]['真实姓名或你喜欢的称呼']);}
    const question=dom.body.appendChild(new Element('p',{class:'mx-draw-question'}));context.MingxueI18n.setLanguage('en');context.MingxueI18n.text(question,'开始时的问题：{question}',{question:'职业方向'});context.MingxueI18n.localize(question.childNodes[0]);assert.ok(question.textContent.endsWith('职业方向'));
  });
  await test('switching UI language preserves data, photos, drafts and only localizes self-report notes',async()=>{
    const e=wellbeingPair({i18n:true});e.node('a-notes').value='User supplied 原文';e.node('question').value='Original question must remain';e.node('cast-same-birthplace').checked=true;e.api.photos.a.push({ref:{id:'a'.repeat(32),kind:'palm_left',sha256:'b'.repeat(64),include_in_report:false}});e.api.photos.b.push({ref:{id:'c'.repeat(32),kind:'portrait',sha256:'d'.repeat(64),include_in_report:false}});e.node('a-wellbeing-mood').value='轻松平稳';await selectWellbeing(e,'career');e.node('a-wellbeing-work').value='分析解决问题';const photos=plain(e.api.photos),draws={...e.draws},markup=e.node('people').innerHTML;
    for(const language of locales){e.node('ui-language').value=language;await e.node('ui-language').fire('change');const request=plain(e.api.collect());assert.equal(request.preferences.ui_language,language);assert.equal(request.preferences.language,'auto');assert.equal(request.preferences.question,'Original question must remain');assert.equal(request.people[0].person.name,'合成测试');assert.ok(request.people[0].person.notes.startsWith('User supplied 原文\n\n'));assert.equal(e.node('a-wellbeing-work').value,'分析解决问题');assert.ok(request.people[0].person.notes.includes(e.i18n.t('分析解决问题')));assert.deepEqual(plain(e.api.photos),photos);assert.deepEqual(e.draws,draws);assert.equal(e.node('people').innerHTML,markup);}
    await selectWellbeing(e,'overview');assert.equal(e.node('a-wellbeing-mood').value,'轻松平稳');
  });
  await test('all four locales display all sixteen presets and ten-question groups in actual collect',async()=>{
    for(const language of locales)for(const [,topic]of presetIds){const e=setup({i18n:true,language});await clickPreset(e,topic);e.node('cast-same-birthplace').checked=true;
      const dom=parse(e.node('a-wellbeing-fields').innerHTML||e.node('people').innerHTML),context={document:{body:dom.body,documentElement:{},getElementById:()=>null},MINGXUE_LOCALES:dictionary};context.window=context;vm.runInNewContext(runtime,context);context.MingxueI18n.setLanguage(language);
      for(const [id,label,options]of e.api.wellbeingQuestions()){
        const select=dom.ids.get('a-wellbeing-'+id);assert.ok(select);assert.equal(select.value,'');assert.ok(dom.body.textContent.includes(e.i18n.t(label)));const choices=select.childNodes.filter(node=>node.tagName==='option');assert.deepEqual(choices.map(option=>option.value),['',...plain(options)]);assert.deepEqual(choices.slice(1).map(option=>option.textContent),plain(options).map(value=>e.i18n.t(value)));e.node('a-wellbeing-'+id).value=options[0];
      }
      const request=plain(e.api.collect());assert.equal(request.preferences.ui_language,language);assert.equal(request.people[0].birth.time,null);assert.ok(request.people[0].person.notes.includes(e.i18n.t(e.api.wellbeingTopics[topic][0])));assert.equal(request.people[0].person.notes.split('\n').length,11);if(language==='en')assert.doesNotMatch(request.preferences.question,/[\u3400-\u9fff]/);requests.push({language,topic,request});}
  });
  await test('foreign name protocol preserves original text and never invents Latin spelling',async()=>{
    for(const [language,full]of [['en',"Alex O'Neil"],['ja','やまだ太郎'],['ko','김민수']]){const e=setup({i18n:true,language});e.node('a-name').value=full;e.node('a-analyze-name').checked=true;assert.deepEqual(plain(e.api.collect()).people[0].name,{mode:'international',full_name:full});e.node('a-name-latin').value=language==='en'?"Alex O'Neil":language==='ja'?'Yamada Taro':'Kim Min-su';e.node('a-name-pronunciation').value='User supplied reading';const request=plain(e.api.collect());assert.equal(request.people[0].name.full_name,full);assert.equal(request.people[0].name.pronunciation,'User supplied reading');requests.push({language,topic:'international-name',request});e.node('a-analyze-name').checked=false;assert.equal(e.api.collect().people[0].name,undefined);}
    const chinese=setup({i18n:true,language:'en'});chinese.node('a-name').value='欧阳若水';chinese.node('a-analyze-name').checked=true;assert.deepEqual(plain(chinese.api.collect()).people[0].name,{surname:'欧阳',given:'若水'});
    const kanji=setup({i18n:true,language:'ja'});kanji.node('a-name').value='山田太郎';kanji.node('a-analyze-name').checked=true;kanji.node('a-name-mode').value='international';await kanji.node('intake').fire('change',{target:kanji.node('a-name-mode')});assert.equal(kanji.api.collect().people[0].name.mode,'international');
  });
  process.stdout.write(JSON.stringify({passed,requests}));
})().catch(error=>{console.error(error);process.exitCode=1;});
