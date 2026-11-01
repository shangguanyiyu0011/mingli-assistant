/* User-clicked draws. No random work occurs during init, update, or apply. */
(function (global) {
  'use strict';
  const MAJORS = ['愚者','魔术师','女祭司','皇后','皇帝','教皇','恋人','战车','力量','隐士','命运之轮','正义','倒吊人','死神','节制','恶魔','高塔','星星','月亮','太阳','审判','世界'];
  const SUITS = [['wands','权杖'],['cups','圣杯'],['swords','宝剑'],['pentacles','星币']];
  const RANKS = [['ace','一'],['02','二'],['03','三'],['04','四'],['05','五'],['06','六'],['07','七'],['08','八'],['09','九'],['10','十'],['page','侍从'],['knight','骑士'],['queen','王后'],['king','国王']];
  const TAROT = MAJORS.map((name,i) => ({id:'major-'+String(i).padStart(2,'0'),name,arcana:'major'}));
  for (const [suit,label] of SUITS) for (const [rank,name] of RANKS) TAROT.push({id:suit+'-'+rank,name:label+name,arcana:'minor',suit});
  const LEN_NAMES = ['骑士','四叶草','船','房子','树','云','蛇','棺材','花束','镰刀','鞭子','鸟','孩子','狐狸','熊','星星','鹳','狗','塔','花园','山','岔路','老鼠','心','戒指','书','信','男士','女士','百合','太阳','月亮','钥匙','鱼','锚','十字架'];
  const LENORMAND = LEN_NAMES.map((name,i) => ({number:i+1,id:'lenormand-'+String(i+1).padStart(2,'0'),name}));
  const TAROT_SPREADS = {single:['一张牌',1],three:['三张牌',3],decision:['选择五牌',5],celtic:['凯尔特十字十牌',10]};
  const LEN_SPREADS = {pair:['两张牌',2],three:['三张牌',3],nine:['九张牌',9],grand:['三十六张大桌阵',36]};
  const ORDER = ['tarot','lenormand','iching','lingqijing','geomancy'];
  const TITLES = {tarot:'塔罗 · 亲手选牌',lenormand:'雷诺曼 · 按顺序选牌',iching:'六次三币 · 从下往上',lingqijing:'灵棋 · 上中下各四枚',geomancy:'土占 · 留下四组点形'};
  const NOTE_KEY = '本次亲手抽取说明';
  let host = null, config = {}, active = new Set(), pair = false, question = '', artSnapshot=[];
  const methodNodes=new Map(),bindingCache=new Map();
  const states = {};
  const clone = value => JSON.parse(JSON.stringify(value));
  const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
  const has = value => value !== undefined && value !== null && !(typeof value === 'string' && !value.trim()) && !(Array.isArray(value) && !value.length);
  const tr=(source,values)=>global.MingxueI18n?.t(source,values)??String(source).replace(/\{(\w+)\}/g,(whole,key)=>values&&key in values?String(values[key]):whole);
  function setText(node,source,values){if(global.MingxueI18n?.text)return global.MingxueI18n.text(node,source,values);node.textContent=tr(source,typeof values==='function'?values():values);return node;}
  function setAttr(node,name,source,values){if(global.MingxueI18n?.attr)return global.MingxueI18n.attr(node,name,source,values);node.setAttribute(name,tr(source,typeof values==='function'?values():values));return node;}
  function fresh(id,previous) { return {id,started:false,open:previous ? previous.open : id==='tarot',spread:previous ? previous.spread : 'three',layout:previous ? previous.layout : '9x4',reversals:previous ? previous.reversals : true,question:'',pair:false,deck:[],picked:[],slots:[],rows:[],error:''}; }
  for (const id of ORDER) states[id] = fresh(id);

  function selected(value) {
    if (value === 'all') return new Set([...ORDER,'yilin']);
    if (Array.isArray(value) || value instanceof Set || value && typeof value[Symbol.iterator] === 'function' && typeof value !== 'string') return new Set(value);
    return new Set();
  }
  function shown(id,selection) { return selection.has(id) || id === 'iching' && selection.has('yilin'); }
  function count(s) { return s.id==='tarot' ? TAROT_SPREADS[s.spread][1] : s.id==='lenormand' ? LEN_SPREADS[s.spread][1] : s.id==='iching' ? 6 : s.id==='lingqijing' ? 3 : 4; }
  function progress(s) { return s.id==='tarot' || s.id==='lenormand' ? s.picked.length : s.rows.length; }
  function complete(s) { return s.started && progress(s) === count(s); }
  function fail(message,code) { const error = new Error(message); error.code=code || 'draw_not_ready'; return error; }
  function below(bound) {
    if (!global.crypto || typeof global.crypto.getRandomValues !== 'function') throw fail('暂时不能抽取，请稍后重试，或改用实物抽取。');
    const limit = Math.floor(0x100000000 / bound) * bound, buffer = new Uint32Array(1);
    for (let attempt=0;attempt<256;attempt++) { global.crypto.getRandomValues(buffer); if(buffer[0]<limit)return buffer[0]%bound; }
    throw fail('这次没有顺利抽到，请稍后再试；原来留下的结果不会被盖掉。');
  }
  function shuffle(deck) { const out=deck.slice(); for (let i=out.length-1;i>0;i--) { const j=below(i+1); [out[i],out[j]]=[out[j],out[i]]; } return out; }
  function validQuestion(id) {
    if (!question.trim() || !/[\p{L}\p{N}]/u.test(question)) throw fail('请先用一句话写下这次想问的事，再开始。','question_required');
    const maximum = id==='lenormand' || id==='geomancy' ? 2000 : 4000;
    if (question.length>maximum) throw fail('这段问题较长，请先缩成一句清楚的话；原来写的内容仍会保留。','question_too_long');
  }
  function act(id,fn,slot) { const s=states[id]; try { fn(s); s.error=''; } catch (error) { s.error=error.message; } render(id,slot); }
  function begin(id) {
    act(id,old => {
      validQuestion(id);
      // Generate the new deck before replacing an existing completed draw.
      const deck=id==='tarot' ? shuffle(TAROT) : id==='lenormand' ? shuffle(LENORMAND) : [];
      const s=fresh(id,old); s.started=true; s.open=true; s.question=question.trim(); s.pair=pair; s.deck=deck;
      states[id]=s;
    });
  }
  function pick(id,slot) {
    const current=states[id];
    if (!current.started || complete(current) || current.slots.includes(slot) || !Number.isInteger(slot) || !current.deck[slot]) return;
    act(id,s => {
      const card=s.deck[slot], orientation=id==='tarot' ? (s.reversals && below(2) ? 'reversed' : 'upright') : null;
      s.slots.push(slot); s.picked.push({...card,...(orientation ? {orientation} : {})});
    },slot);
  }
  function toss(id) {
    act(id,s => {
      if (!s.started || complete(s)) return;
      const bits=Array.from({length:id==='iching' ? 3 : 4},()=>below(2));
      s.rows.push(bits);
    });
  }
  function safeSrc(value) {
    if (typeof value!=='string') return '';
    return /^data:image\/(?:png|jpeg|webp|avif|gif|svg\+xml)[;,]/i.test(value) || /^\/(?!\/)[^\s]*$/.test(value) ? value : '';
  }
  function art() { return config.art || global.MingxueArt || {}; }
  function cardBack() { return safeSrc(config.backUrl || art().card_back && art().card_back.src || ''); }
  function mapRows(mapping) {
    if (Array.isArray(mapping)) return mapping.map((row,index)=>typeof row==='string'?{card_id:row,index}:row&&typeof row==='object'?{index,...row}:null).filter(Boolean);
    if (!mapping || typeof mapping!=='object') return [];
    return Object.entries(mapping).map(([key,value])=>Number.isInteger(value)?{card_id:key,index:value}:/^\d+$/.test(key)&&typeof value==='string'?{card_id:value,index:Number(key)}:null).filter(Boolean);
  }
  function matchesCard(entry,card) {
    if (typeof entry.card_id==='string' && entry.card_id) return entry.card_id===card.id;
    return typeof entry.name==='string' && entry.name.length>0 && entry.name===card.name;
  }
  function refreshArtCache() {
    const next=Object.entries(art()).map(([key,entry])=>[key,entry.src,entry.width,entry.height,JSON.stringify(entry.atlas)]);
    if(next.length!==artSnapshot.length||next.some((row,i)=>row.some((value,j)=>value!==artSnapshot[i][j]))){bindingCache.clear();artSnapshot=next;return true;}return false;
  }
  function artBinding(id,card) {
    const key=id+':'+card.id;if(!bindingCache.has(key))bindingCache.set(key,computeArtBinding(id,card));return bindingCache.get(key);
  }
  function computeArtBinding(id,card) {
    const suit=id==='tarot' && /^(wands|cups|swords|pentacles)-/.exec(card.id);
    const keys=id==='tarot' ? [card.id.startsWith('major-')?'tarot_major':suit?'tarot_'+suit[1]:''] : id==='lenormand'?['lenormand']:[];
    const matches=[];
    for (const key of keys) {
      const entry=art()[key], atlas=entry && entry.atlas;
      if (!atlas || atlas.verified_for_card_binding!==true || !Number.isFinite(entry.width) || !Number.isFinite(entry.height) || entry.width<=0 || entry.height<=0) continue;
      const src=safeSrc(entry.src); if(!src)continue;
      const mappings=mapRows(atlas.index_mapping),hasTiles=Array.isArray(atlas.tiles)&&atlas.tiles.length>0;
      const rows=hasTiles?atlas.tiles:mappings, windows=[];
      for(let i=0;i<rows.length;i++) {
        const raw=rows[i]; if(!raw || typeof raw!=='object')continue;
        const linked=hasTiles?mappings.find(row=>row.index===raw.index):null;
        const identity=raw.card_id||raw.name?raw:linked||raw;
        let box;
        if(hasTiles || ['x','y','width','height'].every(field=>Number.isFinite(raw[field]))) {
          if(!['x','y','width','height'].every(field=>Number.isFinite(raw[field])))continue;
          box={x:raw.x,y:raw.y,width:raw.width,height:raw.height};
        } else {
          if(!Number.isInteger(atlas.cols)||!Number.isInteger(atlas.rows)||atlas.cols<1||atlas.rows<1)continue;
          const index=Number.isInteger(raw.index)?raw.index:i;
          const row=Number.isInteger(raw.row)?raw.row:Math.floor(index/atlas.cols),col=Number.isInteger(raw.col)?raw.col:index%atlas.cols;
          if(row<0||row>=atlas.rows||col<0||col>=atlas.cols)continue;
          box={x:col*entry.width/atlas.cols,y:row*entry.height/atlas.rows,width:entry.width/atlas.cols,height:entry.height/atlas.rows};
        }
        if(box.x<0||box.y<0||box.width<=0||box.height<=0||box.x+box.width>entry.width+1e-7||box.y+box.height>entry.height+1e-7)continue;
        windows.push({identity,box,key,src,assetWidth:entry.width,assetHeight:entry.height});
      }
      for(const item of windows) {
        if(!matchesCard(item.identity,card))continue;
        if(windows.filter(other=>other.box.x===item.box.x&&other.box.y===item.box.y&&other.box.width===item.box.width&&other.box.height===item.box.height).length!==1)continue;
        matches.push({key:item.key,src:item.src,box:item.box,assetWidth:item.assetWidth,assetHeight:item.assetHeight});
      }
    }
    return matches.length===1?matches[0]:null;
  }
  function el(tag,className,text) { const node=host.ownerDocument.createElement(tag); if (className) node.className=className; if (text!==undefined&&text!=='') setText(node,String(text)); return node; }
  function append(parent,...children) { for (const child of children) parent.appendChild(child); return parent; }
  function button(text,action,id,fn) { const node=el('button','mx-draw-button',text); node.type='button'; node.dataset.action=action; node.dataset.system=id; node.addEventListener('click',fn); return node; }
  function selectControl(s,label,values,key) {
    const wrap=el('label','mx-draw-option',label),node=el('select'); node.dataset.control=key; node.dataset.system=s.id; node.disabled=s.started;
    for (const [value,definition] of Object.entries(values)) { const option=el('option','',Array.isArray(definition)?definition[0]:definition); option.value=value; node.appendChild(option); }
    node.value=s[key]; node.addEventListener('change',()=>{ if (!s.started && Object.prototype.hasOwnProperty.call(values,node.value)) { s[key]=node.value; render(s.id); } });
    wrap.appendChild(node); return wrap;
  }
  function drawCard(s,slot) {
    const index=s.slots.indexOf(slot),card=index>=0 ? s.picked[index] : null;
    const node=button('', 'pick',s.id,()=>pick(s.id,slot)); node.dataset.slot=String(slot); node.className='mx-draw-card'+(card?' is-picked':'');
    node.disabled=!!card || complete(s);
    if(card)setAttr(node,'aria-label','第{n}张：{name}{orientation}',()=>({n:index+1,name:tr(card.name),orientation:card.orientation==='reversed'?tr('，逆位'):card.orientation?tr('，正位'):''}));else setAttr(node,'aria-label','选择牌背位置{n}',{n:slot+1});
    const picture=el('span','mx-draw-card-picture'); picture.setAttribute('aria-hidden','true');
    if (card) {
      const binding=artBinding(s.id,card);
      if(binding) {
        const box=binding.box,image=el('img','mx-draw-atlas-image');image.src=binding.src;image.alt='';image.draggable=false;
        picture.style.aspectRatio=box.width+' / '+box.height;picture.style.minHeight='0';picture.style.border='0';
        Object.assign(image.style,{position:'absolute',width:(binding.assetWidth/box.width*100)+'%',height:(binding.assetHeight/box.height*100)+'%',left:(-box.x/box.width*100)+'%',top:(-box.y/box.height*100)+'%',maxWidth:'none',maxHeight:'none'});
        picture.appendChild(image);
      } else picture.textContent=s.id==='tarot' ? '✦' : '◇';
      if (card.orientation==='reversed') picture.className+=' is-reversed';
      const caption=el('span','mx-draw-card-caption');setText(caption,'第{n}张{orientation}',()=>({n:index+1,orientation:card.orientation?' · '+tr(card.orientation==='reversed'?'逆位':'正位'):''}));
      append(node,picture,el('span','mx-draw-card-name',card.name),caption);
    } else {
      if (!cardBack()) picture.textContent='✦';
      append(node,picture,el('span','mx-draw-card-caption','选这里'));
    }
    return node;
  }
  function coinRow(bits,id,index) {
    const row=el('div','mx-draw-cast-row'), labels=id==='iching' ? ['初爻','二爻','三爻','四爻','五爻','上爻'] : id==='lingqijing' ? ['上组','中组','下组'] : ['第一母','第二母','第三母','第四母'];
    append(row,el('strong','mx-draw-row-label',labels[index]));
    for (const bit of bits) {
      const token=el('span',id==='geomancy'?'mx-draw-dots':'mx-draw-coin',id==='geomancy' ? (bit?'•':'••') : (bit?'正':'反'));
      token.setAttribute('aria-label',id==='geomancy' ? (bit?'单点':'双点') : (bit?'正面':'反面'));
      const coins=safeSrc(art().coins && art().coins.src); if (id!=='geomancy' && coins) token.style.backgroundImage='url('+JSON.stringify(coins)+')';
      row.appendChild(token);
    }
    const result=id==='iching' ? 6+bits.reduce((a,b)=>a+b,0) : id==='lingqijing' ? bits.reduce((a,b)=>a+b,0) : bits.map(bit=>bit?'1':'2').join('');
    append(row,el('span','mx-draw-row-result',id==='iching' ? String(result)+' · '+({6:'老阴',7:'少阳',8:'少阴',9:'老阳'})[result] : id==='lingqijing' ? String(result)+' 枚正面' : '从上往下 '+result));
    return row;
  }
  function renderMethod(id) {
    const s=states[id],section=el('details','mx-draw-method'); section.open=s.open; section.dataset.system=id;
    section.addEventListener('toggle',()=>{s.open=section.open;});
    const title=id==='iching' && active.has('yilin') ? (active.has('iching')?'周易与易林 · 共用这组六爻':'易林 · 亲手投六爻') : TITLES[id];
    append(section,el('summary','mx-draw-title',title+'　'+(s.started ? progress(s)+' / '+count(s) : '可选')));
    const body=el('div','mx-draw-body');
    const directions=id==='tarot'||id==='lenormand' ? '先洗牌，再点选牌背。你点下的先后，就是保留的牌序。' : id==='iching' ? '每次投三枚，正面记三、反面记二；六次从初爻往上保留。' : id==='lingqijing' ? '上、中、下各投四枚，逐组保留正反；全为反面也会照原样留下。' : '每次留下四行单点或双点，从上到下为火、风、水、土；四组依次保留。';
    append(body,el('p','mx-draw-help',directions));
    if (id==='iching' && active.has('iching') && active.has('yilin')) append(body,el('p','mx-draw-help','周易和易林会读取同一组六爻，不另投一次，也不把它当成两份相互验证。'));
    const controls=el('div','mx-draw-controls');
    if (id==='tarot'||id==='lenormand') controls.appendChild(selectControl(s,'想留几张',id==='tarot'?TAROT_SPREADS:LEN_SPREADS,'spread'));
    if (id==='lenormand' && s.spread==='grand') controls.appendChild(selectControl(s,'排列方式',{'9x4':'每行九张，共四行','8x4+4':'每行八张，另留四张'},'layout'));
    if (id==='tarot') {
      const label=el('label','mx-draw-check'), check=el('input'); check.type='checkbox'; check.checked=s.reversals; check.disabled=s.started; check.dataset.control='reversals'; check.dataset.system=id;
      check.addEventListener('change',()=>{if(!s.started)s.reversals=check.checked;}); append(label,check,el('span','','包含逆位')); controls.appendChild(label);
    }
    controls.appendChild(button(s.started ? (id==='tarot'||id==='lenormand'?'重开并重新洗牌':'重开这一次') : (id==='tarot'||id==='lenormand'?'开始洗牌':'开始这一次'),'start',id,()=>begin(id)));
    if (s.started) controls.appendChild(button('本页先略过','skip',id,()=>{states[id]=fresh(id,s);render(id);}));
    body.appendChild(controls);
    if (s.error) { const error=el('p','mx-draw-error',s.error); error.setAttribute('role','alert'); body.appendChild(error); }
    if (s.started) {
      const questionNode=el('p','mx-draw-question');setText(questionNode,'开始时的问题：{question}',{question:s.question});append(body,questionNode);
      const notice=el('p','mx-draw-notice','问题或人数已改动，刚才的提问与抽取仍保留。如想按现在的共同问题重新来，请点上方重开；不会自行重抽。');notice.hidden=s.question===question.trim()&&s.pair===pair;append(body,notice);
      const status=el('p','mx-draw-status');if(complete(s))setText(status,'已经留好，可以随资料一起提交。');else setText(status,id==='tarot'||id==='lenormand'?'还差 {n} 张。':'还差 {n} 次。',{n:count(s)-progress(s)});status.setAttribute('aria-live','polite'); body.appendChild(status);
      if (id==='tarot'||id==='lenormand') {
        const grid=el('div','mx-draw-pool'); grid.dataset.cardPool=id;
        if (!complete(s)) { const back=cardBack(); if(back)grid.style.setProperty('--mx-draw-back','url('+JSON.stringify(back)+')'); }
        for (const slot of complete(s)?s.slots:s.deck.map((_,i)=>i)) grid.appendChild(drawCard(s,slot));
        if (complete(s)) finishPool(grid,s);
        body.appendChild(grid);
        const list=el('ol','mx-draw-picked'); for (const card of s.picked) list.appendChild(el('li','',card.name+(card.orientation?' · '+(card.orientation==='reversed'?'逆位':'正位'):''))); body.appendChild(list);
      } else {
        const board=el('div','mx-draw-cast'); const indexes=s.rows.map((_,i)=>i); if(id==='iching')indexes.reverse();
        for (const index of indexes) board.appendChild(coinRow(s.rows[index],id,index));
        body.appendChild(board);
        if (!complete(s)) {
          const action=button('','toss',id,()=>toss(id));
          if(id==='lingqijing')setText(action,'投{group}四枚',()=>({group:tr(['上组','中组','下组'][s.rows.length])}));else setText(action,id==='iching'?'投第 {n} 次三币':'取第 {n} 组点形',{n:s.rows.length+1});
          body.appendChild(action);
        }
      }
    }
    section.appendChild(body); return section;
  }
  function finishPool(pool,s) {
    const cards=new Map(Array.from(pool.children,node=>[Number(node.dataset.slot),node]));
    pool.replaceChildren(...s.slots.map(slot=>cards.get(slot)));
    pool.classList.add('is-complete');pool.dataset.layout=s.id==='lenormand'?(s.spread==='grand'?s.layout:s.spread==='nine'?'3x3':'line'):'line';
    pool.style.removeProperty('--mx-draw-back');
  }
  function render(id,slot) {
    if (!host) return;
    const previous=methodNodes.get(id),s=states[id];
    if(previous&&shown(id,active)){
      const pool=previous.querySelector('.mx-draw-pool');
      if(Number.isInteger(slot)&&pool&&s.started&&!s.error){
        pool.replaceChild(drawCard(s,slot),pool.children[slot]);
        if(complete(s))finishPool(pool,s);
        if(complete(s))setText(previous.querySelector('.mx-draw-status'),'已经留好，下面按选牌顺序排列，可以随资料一起提交。');else setText(previous.querySelector('.mx-draw-status'),'还差 {n} 张。',{n:count(s)-progress(s)});
        setText(previous.querySelector('summary'),'{title}　{progress} / {count}',()=>({title:tr(TITLES[id]),progress:progress(s),count:count(s)}));
        const card=s.picked[s.picked.length-1],list=previous.querySelector('.mx-draw-picked');list.appendChild(el('li','',card.name+(card.orientation?' · '+(card.orientation==='reversed'?'逆位':'正位'):'')));
        return;
      }
      const next=renderMethod(id);host.replaceChild(next,previous);methodNodes.set(id,next);return;
    }
    methodNodes.clear();
    host.replaceChildren(); const ids=ORDER.filter(id=>shown(id,active)); host.hidden=!ids.length;
    if (!ids.length) return;
    host.classList.add('mx-draws');
    append(host,el('h3','mx-draw-heading','在这里亲手抽取'),el('p','mx-draw-intro','这些都可以选做。先写下明确的问题，再开始；没开始的可以先略过，已经开始的请完成，或选“本页先略过”。'));
    const shared=el('p','mx-draw-shared','两人只共用一组来回应共同的问题。各自的报告会复用同一份，不是两次独立抽取，也不能当成相互验证。');shared.hidden=!pair;append(host,shared);
    for (const id of ids){const node=renderMethod(id);host.appendChild(node);methodNodes.set(id,node);}
  }
  function manual(id,s) {
    if (id==='tarot') return {spread:s.spread,cards:s.picked.map(card=>card.id+':'+card.orientation),question:s.question};
    if (id==='lenormand') return {spread:s.spread,layout:s.spread==='grand'?s.layout:s.spread==='nine'?'3x3':'line',cards:s.picked.map(card=>card.number),question:s.question};
    if (id==='iching') return {method:'manual',lines:s.rows.map(bits=>6+bits.reduce((a,b)=>a+b,0)),direction:'bottom-to-top',question:s.question};
    if (id==='yilin') return {method:'lines',lines:s.rows.map(bits=>6+bits.reduce((a,b)=>a+b,0)),question:s.question};
    if (id==='lingqijing') return {method:'counts',counts:s.rows.map(bits=>bits.reduce((a,b)=>a+b,0)),question:s.question};
    return {mothers:s.rows.map(bits=>bits.map(bit=>bit?'1':'2').join('')),question:s.question};
  }
  function mergeMethod(request,id,data) {
    const existing=request.method_options[id] || {};
    if (typeof existing!=='object' || Array.isArray(existing)) throw fail('另有一份'+(TITLES[id]||'易林')+'填写记录，请先检查后再继续。','manual_conflict');
    const manualKeys=id==='tarot'||id==='lenormand'?['cards']:id==='iching'?['lines','numbers']:id==='yilin'?['base','changed','lines','iching_result']:id==='lingqijing'?['counts','pieces']:['mothers','point_counts'];
    for (const key of manualKeys) {
      let value=existing[key], expected=data[key];
      if (id==='tarot' && key==='cards' && typeof value==='string') value=value.split(',').map(piece=>piece.trim());
      if (has(value) && (expected===undefined || !same(value,expected))) throw fail((TITLES[id]||'易林')+'另有一份不同的记录，请先决定保留哪一份，不会替你盖掉。','manual_conflict');
    }
    for (const key of ['spread','layout','question']) if (has(existing[key]) && data[key]!==undefined && existing[key]!==data[key]) throw fail((TITLES[id]||'易林')+'另有不同的选法或提问，请先决定保留哪一份。','manual_conflict');
    const merged={...existing,...data}; delete merged.seed;
    if (id==='tarot') delete merged.upright_only;
    request.method_options[id]=merged;
  }
  function operationNotes(done,selection,currentPair,currentQuestion) {
    const notes=['这是资料页实际点击留下的操作记录，与用户自述分开。'+(currentPair?'两人共用一组，各自报告复用同一份；不是两次独立抽取，不能作为相互验证。':'以下结果均由本次在页面上亲自点击留下。')];
    const groups=new Map();
    for (const s of done) {
      const name=s.id==='iching' && selection.has('yilin') ? (selection.has('iching')?'周易与易林共用六爻':'易林六爻') : TITLES[s.id].split(' · ')[0];
      const sequence=s.id==='tarot'||s.id==='lenormand' ? s.picked.map((card,i)=>(i+1)+'.'+card.name+(card.orientation?'('+ (card.orientation==='reversed'?'逆位':'正位') +')':'')).join('、') : s.id==='iching' ? '从下往上：'+manual('iching',s).lines.join('、') : s.id==='lingqijing' ? '上、中、下正面数：'+manual(s.id,s).counts.join('、') : '第一至第四母，各从上往下：'+manual(s.id,s).mothers.join('、');
      notes.push(name+'｜开始时为'+(s.pair?'两人共同提问':'个人提问')+'；实际顺序：'+sequence+'。'+(s.question!==currentQuestion||s.pair!==currentPair?'后来问题或人数有变，仍保留开始时的提问与原结果，没有重新抽取。':''));
      if (!groups.has(s.question)) groups.set(s.question,[]); groups.get(s.question).push(name);
    }
    for (const [original,names] of groups) {
      const header='开始时的提问原文（'+names.join('、')+'）：';
      for(let offset=0;offset<original.length;offset+=1800) notes.push((offset===0?header:'原提问续：')+original.slice(offset,offset+1800));
    }
    if (notes.length>20 || notes.some(note=>note.length>2000)) throw fail('这次的抽取记录较长，请分开整理后再提交。','draw_notes_too_long');
    return notes;
  }
  function apply(request,selection) {
    if (!request || typeof request!=='object' || Array.isArray(request)) throw fail('这份资料还没有整理好，请检查后重试。');
    const wanted=selected(selection===undefined?active:selection), done=[];
    for (const id of ORDER) {
      const s=states[id]; if (!shown(id,wanted) || !s.started) continue;
      if (!complete(s)) throw fail((TITLES[id]||'这次抽取')+'还没有完成，请继续，或选择“本页先略过”。','unfinished_draw');
      done.push(s);
    }
    const output=clone(request);
    if (!done.length) return output;
    if (!output.method_options) output.method_options={};
    if (typeof output.method_options!=='object' || Array.isArray(output.method_options)) throw fail('另有的填写记录还没有整理好，请检查后重试。');
    for (const s of done) {
      if (s.id==='iching') { if(wanted.has('iching'))mergeMethod(output,'iching',manual('iching',s)); if(wanted.has('yilin'))mergeMethod(output,'yilin',manual('yilin',s)); }
      else mergeMethod(output,s.id,manual(s.id,s));
    }
    output.preferences=output.preferences || {}; const answers=output.preferences.answers || {};
    if (typeof answers!=='object' || Array.isArray(answers)) throw fail('补充说明还没有整理好，请检查后再提交。');
    const notes=operationNotes(done,wanted,output.mode==='pair',typeof output.preferences.question==='string'?output.preferences.question.trim():question.trim());
    if (Object.prototype.hasOwnProperty.call(answers,NOTE_KEY)) {
      if (!same(answers[NOTE_KEY],notes)) throw fail('补充说明里已有另一份“本次亲手抽取说明”，请先决定保留哪一份。','operation_note_conflict');
    } else {
      if (Object.keys(answers).length>=50) throw fail('补充说明已经较多，请先腾出一项，再带上这次的抽取记录。','answer_capacity');
      answers[NOTE_KEY]=notes;
    }
    output.preferences.answers=answers; return output;
  }
  const api={
    init(element,options) { if (!element || !element.ownerDocument) throw fail('抽取位置暂时没有打开，请重新进入资料页。'); host=element; config={...(options||{})}; refreshArtCache();render(); return api; },
    update(selection,options) { const next=selected(selection),changed=next.size!==active.size||[...next].some(id=>!active.has(id));active=next;const values=options||{};if(Object.prototype.hasOwnProperty.call(values,'pair'))pair=values.pair===true;if(Object.prototype.hasOwnProperty.call(values,'question'))question=typeof values.question==='string'?values.question:'';const artChanged=refreshArtCache();if(changed||artChanged)render();else if(host){const shared=host.querySelector('.mx-draw-shared');if(shared)shared.hidden=!pair;for(const [id,node] of methodNodes){const notice=node.querySelector('.mx-draw-notice');if(notice)notice.hidden=states[id].question===question.trim()&&states[id].pair===pair;}}return api; },
    apply,
    getCatalog() { return clone({tarot:TAROT,lenormand:LENORMAND,tarotSpreads:TAROT_SPREADS,lenormandSpreads:LEN_SPREADS}); },
    getArtBinding(system,cardId) { refreshArtCache();const card=(system==='tarot'?TAROT:system==='lenormand'?LENORMAND:[]).find(value=>value.id===cardId);return card?clone(artBinding(system,card)):null; },
    getState() { const out={pair,question,active:[...active],methods:{}}; for(const id of ORDER){const s=states[id];out.methods[id]={started:s.started,complete:complete(s),spread:s.spread,layout:s.layout,question:s.question,pair:s.pair,picked:clone(s.picked),rows:clone(s.rows),slots:s.slots.slice(),error:s.error};}return out; }
  };
  global.MingxueDraws=Object.freeze(api);
})(typeof window!=='undefined'?window:globalThis);
