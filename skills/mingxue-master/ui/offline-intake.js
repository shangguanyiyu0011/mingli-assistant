(() => {
'use strict';
const catalog=window.OFFLINE_CATALOG,photos=new Map(),enc=new TextEncoder(),MAX=6*1024*1024,TOTAL=30*1024*1024;
const randomId=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');
const id=randomId();let packing=false;
const crcTable=Array.from({length:256},(_,i)=>{let c=i;for(let j=0;j<8;j++)c=(c&1)?0xedb88320^(c>>>1):c>>>1;return c>>>0});
function crc(data){let c=0xffffffff;for(const b of data)c=crcTable[(c^b)&255]^(c>>>8);return (c^0xffffffff)>>>0}
function orientation(bytes){try{let p=bytes[0]===69&&bytes[1]===120?6:0;const v=new DataView(bytes.buffer,bytes.byteOffset+p,bytes.byteLength-p),le=v.getUint16(0,false)===0x4949;if(!le&&v.getUint16(0,false)!==0x4d4d)return null;if(v.getUint16(2,le)!==42)return null;let off=v.getUint32(4,le),n=v.getUint16(off,le);if(n>4096||off+2+n*12+4>v.byteLength)return null;for(let i=0;i<n;i++){let q=off+2+i*12;if(v.getUint16(q,le)===0x112&&v.getUint16(q+2,le)===3&&v.getUint32(q+4,le)===1){let x=v.getUint16(q+8,le);return x>=1&&x<=8?x:null}}}catch(_){}return null}
function imageInfo(bytes,mime){const v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);let width=0,height=0,orient=null;if(mime==='image/png'){if(bytes.length<33||[137,80,78,71,13,10,26,10].some((x,i)=>bytes[i]!==x))throw Error('请选择有效的 PNG 或 JPEG 图片。');let p=8,first=true,idat=false,end=false;while(p<bytes.length){if(p+12>bytes.length)throw Error('图片文件不完整。');let n=v.getUint32(p),q=p+12+n;if(q>bytes.length)throw Error('图片文件不完整。');let kind=String.fromCharCode(...bytes.slice(p+4,p+8));if(crc(bytes.subarray(p+4,p+8+n))!==v.getUint32(p+8+n))throw Error('图片文件损坏，请换一张。');if(first){if(kind!=='IHDR'||n!==13)throw Error('图片格式不正确。');width=v.getUint32(p+8);height=v.getUint32(p+12);let depth=bytes[p+16],color=bytes[p+17],allowed={0:[1,2,4,8,16],2:[8,16],3:[1,2,4,8],4:[8,16],6:[8,16]};if(!allowed[color]?.includes(depth)||bytes[p+18]||bytes[p+19]||![0,1].includes(bytes[p+20]))throw Error('图片格式不正确。')}else if(kind==='IHDR')throw Error('图片格式不正确。');if(kind==='IDAT'&&n)idat=true;if(kind==='eXIf')orient=orientation(bytes.subarray(p+8,p+8+n));p=q;first=false;if(kind==='IEND'){if(n||p!==bytes.length)throw Error('图片格式不正确。');end=true;break}}if(!end||!idat)throw Error('图片文件不完整。')}else{if(bytes[0]!==255||bytes[1]!==216)throw Error('请选择有效的 PNG 或 JPEG 图片。');let p=2,scan=false,end=false,frames=new Set([192,193,194,195,197,198,199,201,202,203,205,206,207]);while(p<bytes.length){if(bytes[p++]!==255)throw Error('图片格式不正确。');while(p<bytes.length&&bytes[p]===255)p++;let marker=bytes[p++];if(marker===217){end=true;break}if(marker===1)continue;if(marker===0||marker===216||(marker>=208&&marker<=215)||p+2>bytes.length)throw Error('图片格式不正确。');let len=v.getUint16(p);if(len<2||p+len>bytes.length)throw Error('图片文件不完整。');if(frames.has(marker)){if(len<8||![1,3,4].includes(bytes[p+7])||len!==8+3*bytes[p+7])throw Error('图片格式不正确。');height=v.getUint16(p+3);width=v.getUint16(p+5)}if(marker===225&&bytes[p+2]===69&&bytes[p+3]===120)orient=orientation(bytes.subarray(p+2,p+len));p+=len;if(marker===218){scan=true;while(p<bytes.length){if(bytes[p]!==255){p++;continue}let q=p+1;while(bytes[q]===255)q++;if(bytes[q]===0||(bytes[q]>=208&&bytes[q]<=215)){p=q+1;continue}break}}}if(!end||!scan||!width||!height)throw Error('图片文件不完整。')}if(!width||!height||width*height>100000000)throw Error('图片尺寸不受支持。');return {width,height,display_width:[5,6,7,8].includes(orient)?height:width,display_height:[5,6,7,8].includes(orient)?width:height}}
function bytesFromBase64(s){let str=atob(s),a=new Uint8Array(str.length);for(let i=0;i<str.length;i++)a[i]=str.charCodeAt(i);return a}
async function hash(bytes){if(!crypto.subtle)throw Error('浏览器暂时不能校验图片，请重新打开填写页后重试。');return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('')}
async function fileCrc(bytes){let c=0xffffffff;for(let start=0;start<bytes.length;start+=1048576){for(let i=start;i<Math.min(start+1048576,bytes.length);i++)c=crcTable[(c^bytes[i])&255]^(c>>>8);if(start+1048576<bytes.length)await new Promise(resolve=>setTimeout(resolve,0));}return (c^0xffffffff)>>>0}
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
window.photoUrl=photoId=>photos.get(photoId)?.url||'';
async function zip(entries){let chunks=[],central=[],offset=0;for(const e of entries){const name=enc.encode(e.name),data=e.data instanceof Uint8Array?e.data:enc.encode(e.data),checksum=e.checksum??await fileCrc(data),h=new Uint8Array(30+name.length),v=new DataView(h.buffer);v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x800,true);v.setUint32(14,checksum,true);v.setUint32(18,data.length,true);v.setUint32(22,data.length,true);v.setUint16(26,name.length,true);h.set(name,30);chunks.push(h,data);let c=new Uint8Array(46+name.length),w=new DataView(c.buffer);w.setUint32(0,0x02014b50,true);w.setUint16(4,20,true);w.setUint16(6,20,true);w.setUint16(8,0x800,true);w.setUint32(16,checksum,true);w.setUint32(20,data.length,true);w.setUint32(24,data.length,true);w.setUint16(28,name.length,true);w.setUint32(42,offset,true);c.set(name,46);central.push(c);offset+=h.length+data.length}let size=central.reduce((n,x)=>n+x.length,0),tail=new Uint8Array(22),v=new DataView(tail.buffer);v.setUint32(0,0x06054b50,true);v.setUint16(8,entries.length,true);v.setUint16(10,entries.length,true);v.setUint32(12,size,true);v.setUint32(16,offset,true);return new Blob([...chunks,...central,tail],{type:'application/zip'})}
async function save(request){
  if(packing)throw Error('正在准备资料包，请稍候。');
  if(!request||!Array.isArray(request.people)||!['single','pair'].includes(request.mode)||request.people.length!==(request.mode==='single'?1:2))throw Error('请检查填写的人数。');
  packing=true;let url='';
  try{
    const seen=new Set(),selected=[];
    request.people.forEach((person,index)=>{const role=index===0?'A':'B';for(const ref of person.photos||[]){const item=photos.get(ref.id);if(!item||seen.has(ref.id)||item.entry.person!==role||ref.sha256!==item.entry.sha256||ref.kind!==item.entry.kind||typeof ref.include_in_report!=='boolean')throw Error('图片资料已变化，请重新选择。');seen.add(ref.id);selected.push({item,ref});}});
    const manifest={schema_version:1,manifest_type:'private_photos',owner_id:id,photos:selected.map(({item,ref})=>({...item.entry,include_in_report:ref.include_in_report}))};
    const entries=[{name:'request.json',data:JSON.stringify(request,null,2)+'\n'}];
    if(selected.length){entries.push({name:'photos.json',data:JSON.stringify(manifest,null,2)+'\n'});for(const {item} of selected)entries.push({name:item.entry.relative_path,data:item.bytes,checksum:item.checksum});}
    await new Promise(resolve=>setTimeout(resolve,0));
    url=URL.createObjectURL(await zip(entries));
    const a=document.createElement('a');a.href=url;a.download='命学资料包.zip';document.body.appendChild(a);
    try{a.click();}finally{a.remove();}
    window.MingxueDownload={url,filename:a.download};const savedUrl=url;
    window.addEventListener('pagehide',event=>{if(!event.persisted)URL.revokeObjectURL(savedUrl);});
    // Every successful save is immutable; later edits produce a new ZIP.
    url='';
  }finally{packing=false;if(url)URL.revokeObjectURL(url);}
}
window.fetch=async(input,opts={})=>{try{
  const path=typeof input==='string'?input:'';
  if(path==='/api/catalog')return response(catalog);
  if(path==='/api/photos'&&!opts.body)return response({photos:[...photos.values()].map(x=>({...x.entry}))});
  if(packing)throw Error('正在准备资料包，请稍候。');
  if(path==='/api/cancel'){for(const p of photos.values())URL.revokeObjectURL(p.url);photos.clear();return response({status:'cancelled'});}
  const body=JSON.parse(opts.body||'{}');
  if(path==='/api/photos'){
    if(!['A','B'].includes(body.person)||!['palm_left','palm_right','palm_unknown','portrait','room','floorplan','chart','other'].includes(body.kind)||!['image/png','image/jpeg'].includes(body.mime)||typeof body.name!=='string'||!body.name||body.name.length>120||/[\\/:\x00-\x1f]/.test(body.name)||!/\.(?:jpe?g|png)$/i.test(body.name)||body.include_in_report!==false)throw Error('请检查图片和所属人物。');
    if(typeof body.data_base64!=='string'||body.data_base64.length>4*Math.ceil(MAX/3)||body.data_base64.length%4||!/^[A-Za-z0-9+/]*={0,2}$/.test(body.data_base64))throw Error('图片大小或内容不正确。');
    const bytes=bytesFromBase64(body.data_base64);
    if(bytes.length>MAX||!bytes.length)throw Error('图片大小超出限制。');
    const info=imageInfo(bytes,body.mime),sha256=await hash(bytes),checksum=await fileCrc(bytes);
    if(packing)throw Error('正在准备资料包，请稍候。');
    if(photos.size>=12||[...photos.values()].reduce((n,x)=>n+x.bytes.length,0)+bytes.length>TOTAL)throw Error('图片数量或大小超出限制。');
    if([...photos.values()].some(p=>p.entry.sha256===sha256))throw Error('这张图片已经添加，请勿重复选择。');
    const photoId=randomId(),relative_path='private-photos/'+photoId+(body.mime==='image/png'?'.png':'.jpg');
    const entry={id:photoId,person:body.person,kind:body.kind,name:body.name,mime:body.mime,sha256,bytes:bytes.length,...info,include_in_report:false,relative_path,viewed:false,validation:'container_structure_only',pixel_decode_performed:false};
    const url=URL.createObjectURL(new Blob([bytes],{type:body.mime}));photos.set(photoId,{entry,bytes,url,checksum});
    return response({photo:entry,ref:{id:photoId,kind:body.kind,sha256,include_in_report:false}});
  }
  if(path==='/api/photos/remove'){const item=photos.get(body.id);if(!item)throw Error('图片已移除。');URL.revokeObjectURL(item.url);photos.delete(body.id);return response({status:'removed'});}
  if(path==='/api/submit'){await save(body);return response({status:'submitted',files:[],warnings:[],questions:[]});}
  throw Error('页面未能完成操作。');
}catch(e){return response({status:'error',error:e.message||'请检查资料后重试。',warnings:[e.message||'请检查资料后重试。']},400);}};
})();
