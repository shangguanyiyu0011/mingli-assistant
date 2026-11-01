'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),Module=require('node:module'),{webcrypto,createHash}=require('node:crypto');
const {setup,clearWellbeing,plain}=require('./test_intake_form.js');
const root=process.env.MINGXUE_TEST_SKILL_ROOT||path.resolve(__dirname,'..');
// Reuse the existing synthetic DOM, without executing its independent test suite.
const drawPath=path.join(root,'tests/test_intake_draws.js'),domModule=new Module(drawPath);domModule.filename=drawPath;domModule.paths=Module._nodeModulePaths(path.dirname(drawPath));domModule._compile(fs.readFileSync(drawPath,'utf8').split('function setup(options={}){')[0]+'\nmodule.exports={Document};',drawPath);
const {Document}=domModule.exports,PNG=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGMQMgkDIgYIBQAQDgJxg37E2gAAAABJRU5ErkJggg==','base64');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');let passed=0;
function files(bytes){const result={};for(let at=0;bytes.readUInt32LE(at)===0x04034b50;){const size=bytes.readUInt32LE(at+18),length=bytes.readUInt16LE(at+26),extra=bytes.readUInt16LE(at+28),start=at+30+length+extra;result[bytes.subarray(at+30,at+30+length).toString('utf8')]=bytes.subarray(start,start+size);at=start+size;}return result;}
async function environment(language='zh-CN',offline=true){
  const e=setup({offline,i18n:true,language,handler:(url,body,response)=>response({status:'submitted',files:[],warnings:[],questions:[]})}),ctx=e.context;
  await new Promise(resolve=>setImmediate(resolve));
  const doc=new Document(),host=doc.createElement('div'),body=doc.createElement('body'),objects=new Map(),downloads=[],submits=[];body.appendChild(host);let next=0,randomCalls=0;
  const original=ctx.document.getElementById;ctx.document.getElementById=id=>id==='intake-draws'?host:original(id);ctx.document.body=body;
  ctx.document.createElement=tag=>{const node=doc.createElement(tag);node.click=()=>downloads.push(node.href);node.remove=()=>{if(node.parentElement){const nodes=node.parentElement.children;nodes.splice(nodes.indexOf(node),1);node.parentElement=null;}};return node;};
  Object.assign(ctx,{TextEncoder,Uint8Array,DataView,Blob,Response,atob,setTimeout,OFFLINE_CATALOG:{systems:[]},crypto:{subtle:webcrypto.subtle,getRandomValues(array){randomCalls++;return webcrypto.getRandomValues(array);}}});
  ctx.FileReader=class{readAsDataURL(file){file.arrayBuffer().then(buffer=>{this.result='data:'+file.type+';base64,'+Buffer.from(buffer).toString('base64');this.onload();},()=>this.onerror());}};
  ctx.URL.createObjectURL=object=>{const url='blob:export-fixture-'+next++;objects.set(url,object);return url;};ctx.URL.revokeObjectURL=()=>{};
  if(offline)vm.runInNewContext(fs.readFileSync(path.join(root,'ui/offline-intake.js'),'utf8'),ctx);
  const send=ctx.fetch;ctx.fetch=(url,options)=>{if(url==='/api/submit')submits.push(JSON.parse(options.body));return send(url,options);};
  vm.runInNewContext(fs.readFileSync(path.join(root,'ui/intake-draws.js'),'utf8'),ctx);
  e.node('question').value='如何安排学习与合作？';e.node('cast-same-birthplace').checked=true;e.node('virtual-draws').checked=true;
  const find=(system,action,slot)=>{const walk=node=>{if(node.dataset?.system===system&&node.dataset.action===action&&(slot===undefined||node.dataset.slot===String(slot)))return node;for(const child of node.children||[]){const result=walk(child);if(result)return result;}};return walk(host);};
  const click=(system,action,slot)=>{const node=find(system,action,slot);assert.ok(node,system+'/'+action);node.fire('click');};
  const open=async()=>{e.node('draw-options').open=true;await e.node('draw-options').fire('toggle');};
  const again=()=>e.node('result-list').fire('click',{target:{closest:selector=>selector==='[data-download-current]'?{}:null}});
  return {e,ctx,objects,downloads,submits,click,open,again,random:()=>randomCalls,bytes:async url=>Buffer.from(await objects.get(url).arrayBuffer())};
}
const matrix=[];
(async()=>{
  for(const language of ['zh-CN','en','ja','ko']){
    const x=await environment(language);await x.e.node('intake').fire('submit');const firstUrl=x.ctx.MingxueDownload.url,first=await x.bytes(firstUrl),initial=JSON.parse(files(first)['request.json']);assert.equal(x.e.node('submit').disabled,false);assert.equal(initial.method_options,undefined);assert.equal(initial.people[0].person.notes,undefined);assert.doesNotMatch(x.e.node('result-list').innerHTML,/href=/);
    await x.open();x.click('tarot','start');for(let i=0;i<3;i++)x.click('tarot','pick',i);x.click('iching','start');for(let i=0;i<6;i++)x.click('iching','toss');x.e.node('a-wellbeing-mood').value='忙碌充实';
    const input=x.e.node('a-photo-portrait');input.dataset.photoFile='a';input.dataset.photoKind='portrait';input.files=[new File([PNG],'synthetic.png',{type:'image/png'})];await x.e.node('intake').fire('change',{target:input});
    const drawState=plain(x.ctx.MingxueDraws.getState()),current=plain(x.ctx.MingxueIntake.getRequest()),beforeRandom=x.random();assert.ok(current.people[0].person.notes);assert.equal(current.people[0].photos.length,1);
    await Promise.all([x.again(),x.again()]);assert.equal(x.downloads.length,2);assert.equal(x.submits.length,2);assert.equal(x.e.node('submit').disabled,false);assert.equal(x.random(),beforeRandom);assert.deepEqual(plain(x.ctx.MingxueDraws.getState()),drawState);assert.notEqual(x.ctx.MingxueDownload.url,firstUrl);
    const second=await x.bytes(x.ctx.MingxueDownload.url),entries=files(second),request=JSON.parse(entries['request.json']),manifest=JSON.parse(entries['photos.json']);assert.deepEqual(request,x.submits[1]);assert.deepEqual(request.method_options,current.method_options);assert.equal(request.people[0].person.notes,current.people[0].person.notes);assert.deepEqual(request.people[0].photos,current.people[0].photos);assert.equal(request.preferences.ui_language,language);assert.deepEqual(entries[manifest.photos[0].relative_path],PNG);assert.equal(sha(await x.bytes(firstUrl)),sha(first));
    x.click('lenormand','start');x.click('lenormand','pick',0);await x.again();assert.equal(x.downloads.length,2);assert.equal(x.submits.length,2);x.click('lenormand','skip');
    await clearWellbeing(x.e,'a');const target={dataset:{photoRemove:'a',photoIndex:'0'},closest:selector=>selector==='[data-photo-remove]'?target:null};await x.e.node('intake').fire('click',{target});await x.again();assert.equal(x.downloads.length,3);const third=await x.bytes(x.ctx.MingxueDownload.url),last=JSON.parse(files(third)['request.json']);assert.equal(last.people[0].photos,undefined);assert.equal(last.people[0].person.notes,undefined);assert.deepEqual(last.method_options,current.method_options);assert.equal(sha(await x.bytes(firstUrl)),sha(first));assert.equal(sha(second),sha(await x.bytes(x.downloads[1])));
    matrix.push({language,first:initial,current:request,cleared:last,first_zip:first.toString('base64'),current_zip:second.toString('base64'),first_sha256:sha(first),current_sha256:sha(second),random_unchanged:true});passed++;
  }
  const partial=await environment();await partial.open();partial.click('tarot','start');partial.click('tarot','pick',0);partial.click('tarot','pick',1);await partial.e.node('intake').fire('submit');assert.equal(partial.downloads.length,0);partial.click('tarot','pick',2);await partial.e.node('intake').fire('submit');assert.equal(partial.downloads.length,1);assert.equal(JSON.parse(files(await partial.bytes(partial.ctx.MingxueDownload.url))['request.json']).method_options.tarot.cards.length,3);passed++;
  const online=await environment('en',false);await online.ctx.MingxueIntake.download();await online.ctx.MingxueIntake.download();assert.equal(online.submits.length,1);assert.equal(online.e.node('submit').disabled,true);passed++;
  process.stdout.write(JSON.stringify({passed,matrix}));
})().catch(error=>{console.error(error);process.exitCode=1;});
