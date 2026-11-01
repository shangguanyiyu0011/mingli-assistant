'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const root=process.env.MINGXUE_TEST_SKILL_ROOT||path.resolve(__dirname,'..');
process.env.MINGXUE_TEST_SKILL_ROOT=root;
const {setup,plain}=require(path.join(root,'tests/test_intake_form.js'));
const exportPath=path.join(root,'tests/test_intake_export.js'),exportModule=new Module(exportPath);
exportModule.filename=exportPath;exportModule.paths=Module._nodeModulePaths(path.dirname(exportPath));
exportModule._compile(fs.readFileSync(exportPath,'utf8').split('const matrix=[];')[0]+'\nmodule.exports={environment,files,sha};',exportPath);
const {environment,files,sha}=exportModule.exports;
const tests=[],matrix=[];const test=(name,fn)=>tests.push([name,fn]);
const dreamOnly=(e,p='a',text='梦见自己乘船过河，醒来感到平静。')=>{e.node(p+'-dream').value=text;e.node(p+'-date').value='';e.node(p+'-birthplace').value='';e.node(p+'-time-kind').value='exact';};
const selectSystems=(e,ids)=>{e.radios['systems-mode']='custom';e.context.document.querySelectorAll=query=>query.includes('#system-list')?ids.map(value=>({value,checked:true})):[];};

test('dream input is optional, per person and bounded',()=>{
  const e=setup(),markup=e.node('people').innerHTML;
  assert.match(markup,/id="a-dream" rows="3" maxlength="4000"/);assert.match(markup,/id="b-dream" rows="3" maxlength="4000"/);
  assert.equal(e.api.collect().people[0].dream,undefined);
  e.node('a-dream').value='船'.repeat(4001);assert.throws(()=>e.api.collect(),/4000/);
});
test('dream-only auto has no invented birth, place or cast even with a question',()=>{
  const e=setup();e.radios['systems-mode']='auto';dreamOnly(e);e.node('question').value='这场梦里的船和河是什么含义？';e.api.update();
  const data=plain(e.api.collect());assert.equal(data.people[0].birth,null);assert.equal(data.people[0].birthplace,undefined);assert.equal(data.people[0].dream,e.node('a-dream').value);
  assert.equal(data.preferences.cast,undefined);assert.equal(data.preferences.cast_place,undefined);assert.equal(e.node('question-place').hidden,true);
  assert.equal(e.node('a-date').required,false);assert.equal(e.node('a-birthplace').required,false);assert.equal(e.node('a-birth-required').hidden,true);
  e.node('a-dream').value='';e.api.update();assert.equal(e.node('a-date').required,true);assert.equal(e.node('a-birthplace').required,true);assert.throws(()=>e.api.collect(),/出生日期和出生地点/);
});
test('default all lets dream-only users continue without birth or question location',()=>{
  const e=setup();dreamOnly(e);e.node('question').value='想了解梦里的船。';e.api.update();
  const data=plain(e.api.collect());assert.equal(data.preferences.systems,'all');assert.equal(data.people[0].birth,null);
  assert.equal(data.preferences.cast,undefined);assert.equal(data.preferences.cast_place,undefined);assert.equal(e.node('question-place').hidden,true);
});
test('a provided birthday still validates date, birthplace and known time',()=>{
  const e=setup();e.node('a-dream').value='梦见河水。';e.node('a-date').value='2000-14-16';assert.throws(()=>e.api.collect(),/核对出生日期/);
  e.node('a-date').value='2000-08-16';e.node('a-birthplace').value='';assert.throws(()=>e.api.collect(),/填写出生地点/);
  e.node('a-birthplace').value='深圳市';e.node('a-time-kind').value='exact';e.node('a-time').value='24:00';assert.throws(()=>e.api.collect(),/具体出生时间/);
  e.node('a-time-kind').value='shichen';e.node('a-shichen').value='午';assert.equal(e.api.collect().people[0].birth.shichen,'午');assert.equal(e.api.collect().people[0].birth.time,null);
});
test('explicit dream selection needs no cast; explicit Meihua collects its submitted time',()=>{
  const e=setup();dreamOnly(e);selectSystems(e,['dream']);e.node('question').value='请解释这个梦';assert.equal(e.api.collect().preferences.cast,undefined);
  selectSystems(e,['meihua','dream']);e.node('question').value='';e.node('cast-same-birthplace').checked=false;assert.throws(()=>e.api.collect(),/所在的城市/);
  e.node('cast-place').value='北京市，中国';e.node('cast-when').value='past';e.node('cast-datetime').value='2026-10-20T14:00';
  assert.deepEqual(plain(e.api.collect().preferences.cast),{date:'2026-10-20',time:'14:00'});
});
test('A/B dreams and single/pair toggles remain isolated',()=>{
  const e=setup();e.radios.mode='pair';e.radios['systems-mode']='auto';e.node('b-name').value='虚构人物乙';e.node('relationship').value='friend';
  dreamOnly(e,'a','甲梦见蓝色大海。');dreamOnly(e,'b','乙梦见森林与小鸟。');e.api.update();const pair=plain(e.api.collect());
  assert.deepEqual(pair.people.map(p=>p.birth),[null,null]);assert.equal(pair.people[0].dream,'甲梦见蓝色大海。');assert.equal(pair.people[1].dream,'乙梦见森林与小鸟。');
  e.radios.mode='single';e.api.update();assert.equal(e.api.collect().people.length,1);assert.doesNotMatch(JSON.stringify(e.api.collect()),/森林/);
  e.radios.mode='pair';e.api.update();assert.deepEqual(plain(e.api.collect()),pair);
});
test('Meihua alone or with dream needs no birthday but still needs an explicit cast location',()=>{
  const e=setup();e.node('a-date').value='';e.node('a-birthplace').value='';
  for(const selected of [['meihua'],['meihua','dream']]){
    selectSystems(e,selected);e.api.update();assert.equal(e.node('a-date').required,false);assert.equal(e.node('a-birthplace').required,false);
    e.node('cast-place').value='';assert.throws(()=>e.api.collect(),/所在的城市/);
    e.node('cast-place').value='北京市，中国';e.node('cast-when').value='past';e.node('cast-datetime').value='2026-10-20T14:00';
    const request=plain(e.api.collect());assert.equal(request.people[0].birth,null);assert.equal(request.people[0].dream,undefined);assert.deepEqual(request.preferences.cast,{date:'2026-10-20',time:'14:00'});
  }
  e.radios['systems-mode']='all';e.api.update();assert.equal(e.node('a-date').required,true);assert.throws(()=>e.api.collect(),/出生日期和出生地点/);
});
test('four language dictionaries cover new fields and method names without rewriting user dreams',()=>{
  const labels=['梦境描述','梅花易数','周公解梦','面相·麻衣相法','梦境描述请控制在4000字以内。'];
  const dictionaries=['intake-locales.json','report-locales.json'].map(file=>JSON.parse(fs.readFileSync(path.join(root,'ui',file),'utf8')));
  for(const language of ['zh-CN','en','ja','ko']){
    const e=setup({i18n:true,language}),text={ 'zh-CN':'梦见船与河水。','en':'I dreamed of a river and a boat.','ja':'川を船で渡る夢を見ました。','ko':'강을 배로 건너는 꿈을 꾸었습니다。'}[language];
    dreamOnly(e,'a',text);e.radios['systems-mode']='auto';assert.equal(e.api.collect().people[0].dream,text);
    if(language!=='zh-CN')for(const dictionary of dictionaries)for(const label of labels)assert.ok(dictionary[language][label]?.trim(),language+'/'+label);
    e.i18n.setLanguage('zh-CN');assert.equal(e.node('a-dream').value,text);e.i18n.setLanguage(language);assert.equal(e.node('a-dream').value,text);
  }
});
test('dream edits survive four-language ZIP downloads and never reuse the first package',async()=>{
  for(const language of ['zh-CN','en','ja','ko']){
    const x=await environment(language);x.e.radios['systems-mode']='auto';dreamOnly(x.e,'a','A fictitious dream: a river, a boat, and an open door.');
    await x.e.node('intake').fire('submit');const firstUrl=x.ctx.MingxueDownload.url,first=await x.bytes(firstUrl),request1=JSON.parse(files(first)['request.json']);
    assert.equal(request1.people[0].birth,null);assert.equal(request1.preferences.cast,undefined);assert.equal(request1.people[0].dream,x.e.node('a-dream').value);
    x.e.node('a-dream').value='Edited fictitious dream: flying over a blue lake.\nI felt curious.';const before=x.random();await x.again();
    const secondUrl=x.ctx.MingxueDownload.url,second=await x.bytes(secondUrl),request2=JSON.parse(files(second)['request.json']);
    assert.notEqual(firstUrl,secondUrl);assert.equal(request2.people[0].dream,x.e.node('a-dream').value);assert.notEqual(request1.people[0].dream,request2.people[0].dream);
    assert.equal(request2.preferences.ui_language,language);assert.equal(x.random(),before);assert.equal(sha(await x.bytes(firstUrl)),sha(first));
    matrix.push({language,first_sha256:sha(first),second_sha256:sha(second),request:request2});
  }
});
(async()=>{let passed=0;for(const [name,fn]of tests){await fn();passed++;}process.stdout.write(JSON.stringify({passed,matrix}));})().catch(error=>{console.error(error);process.exitCode=1;});
