/* Shared offline UI text translation. Values and user-authored text stay intact. */
(function(global){
  'use strict';
  const languages=['zh-CN','en','ja','ko'],listeners=new Set(),texts=new WeakMap(),attributes=new WeakMap(),bindings=new WeakMap();
  let language='zh-CN',compiled=null;const pageTitle=global.document?.title;
  const dictionary=()=>global.MINGXUE_LOCALES||{};
  const escape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  function entries(locale){
    if(!compiled)compiled=new Map();
    if(!compiled.has(locale)){
      const rows=Object.entries(dictionary()[locale]||{}).filter(([,value])=>typeof value==='string'&&value.trim());
      const literals=rows.filter(([key])=>!key.includes('{')&&key.length>=2).sort((a,b)=>b[0].length-a[0].length);
      const templates=rows.filter(([key])=>/\{\w+\}/.test(key)).map(([key,value])=>{const names=[];let pattern='',offset=0;for(const match of key.matchAll(/\{(\w+)\}/g)){pattern+=escape(key.slice(offset,match.index))+'([\\s\\S]*?)';names.push(match[1]);offset=match.index+match[0].length;}return {pattern:new RegExp('^'+pattern+escape(key.slice(offset))+'$'),names,value};});
      compiled.set(locale,{map:Object.fromEntries(rows),templates,pattern:literals.length?new RegExp(literals.map(([key])=>escape(key)).join('|'),'g'):null});
    }
    return compiled.get(locale);
  }
  function t(source,values,locale=language){
    source=String(source??'');let result=source;
    if(locale!=='zh-CN'){
      const data=entries(locale),trimmed=source.trim();
      result=data.map[source]||data.map[trimmed]&&source.replace(trimmed,data.map[trimmed])||(data.pattern?source.replace(data.pattern,key=>data.map[key]):source);
      if(!data.map[source]&&!data.map[trimmed])for(const template of data.templates){const match=source.match(template.pattern);if(match){const replacements=Object.fromEntries(template.names.map((name,index)=>[name,t(match[index+1],undefined,locale)]));result=template.value.replace(/\{(\w+)\}/g,(whole,key)=>replacements[key]??whole);break;}}
    }
    if(values)result=result.replace(/\{(\w+)\}/g,(whole,key)=>Object.prototype.hasOwnProperty.call(values,key)?String(values[key]):whole);
    return result;
  }
  function values(value){return typeof value==='function'?value():value;}
  function text(node,source,replacements){bindings.set(node,{source,replacements});node.textContent=t(source,values(replacements));return node;}
  function attr(node,name,source,replacements){const saved=attributes.get(node)||{};saved[name]={source,replacements,rendered:t(source,values(replacements))};attributes.set(node,saved);node.setAttribute(name,saved[name].rendered);return node;}
  function ignored(element){return !!element?.closest?.('[data-i18n-ignore],textarea,input,.mx-draw-question,.photo-item span');}
  function localize(root){
    if(!root)return;
    function walk(node){
      if(node.nodeType===3){
        if(ignored(node.parentElement))return;
        const old=texts.get(node),source=old&&node.data===old.rendered?old.source:node.data,rendered=t(source);
        texts.set(node,{source,rendered});if(node.data!==rendered)node.data=rendered;return;
      }
      if(node.nodeType!==1&&node.nodeType!==9&&node.nodeType!==11)return;
      if(node.nodeType===1){
        if(node.matches?.('script,style,[data-i18n-ignore]'))return;
        const saved=attributes.get(node)||{};
        for(const name of ['placeholder','title','aria-label','alt']){
          const value=node.getAttribute?.(name);if(value===null||value===undefined)continue;
          const prior=saved[name],source=prior&&value===prior.rendered?prior.source:value,rendered=t(source,values(prior?.replacements));
          saved[name]={source,rendered,replacements:prior?.replacements};if(value!==rendered)node.setAttribute(name,rendered);
        }
        attributes.set(node,saved);
        const binding=bindings.get(node);if(binding){const rendered=t(binding.source,values(binding.replacements));if(node.textContent!==rendered)node.textContent=rendered;return;}
      }
      for(const child of node.childNodes||[])walk(child);
    }
    walk(root);
  }
  function setLanguage(value){
    if(!languages.includes(value))return false;
    language=value;if(global.document?.documentElement)global.document.documentElement.lang=value;
    if(pageTitle)global.document.title=t(pageTitle);
    localize(global.document?.body);for(const callback of listeners)callback(value);return true;
  }
  global.MingxueI18n={t,text,attr,localize,getLanguage:()=>language,setLanguage,languages:languages.slice(),subscribe(callback){listeners.add(callback);return()=>listeners.delete(callback);},refresh(){compiled=null;localize(global.document?.body);}};
  if(global.document?.body){
    const source=global.document.getElementById?.('intake-locales');
    if(source&&!global.MINGXUE_LOCALES)try{global.MINGXUE_LOCALES=JSON.parse(source.textContent);}catch(_){}
    localize(global.document.body);
    if(global.MutationObserver)new MutationObserver(records=>{for(const record of records){if(record.type==='childList')for(const node of record.addedNodes)localize(node);else localize(record.target);}}).observe(global.document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['placeholder','title','aria-label','alt']});
  }
})(typeof window!=='undefined'?window:globalThis);
