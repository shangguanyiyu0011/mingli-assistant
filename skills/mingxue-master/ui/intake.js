(() => {
'use strict';
const $=id=>document.getElementById(id), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const tr=(source,values,language)=>window.MingxueI18n?.t(source,values,language)??String(source).replace(/\{(\w+)\}/g,(whole,key)=>values&&key in values?String(values[key]):whole);
const uiLanguage=()=>window.MingxueI18n?.getLanguage()||'zh-CN',nameModesInitialized=new Set();
const friendly=(value,fallback='操作未完成，请检查资料后重试。')=>{const t=typeof value==='string'?value:'';return !t||/JSON|HTTP|API|token|schema|hash|权限|接口|引擎|配置|服务|[A-Za-z]{3,}/i.test(t)?fallback:t};
const offlineMode=window.MINGXUE_OFFLINE===true;
const hash=new URLSearchParams(location.hash.slice(1));let token=document.querySelector('meta[name="workbench-token"]')?.content||hash.get('token')||'';try{if(token)sessionStorage.setItem('mingxue_token',token);else token=sessionStorage.getItem('mingxue_token')||'';}catch(_){}if(location.hash&&!offlineMode)history.replaceState(null,'',location.pathname+location.search);
let systems=[],busy=false,submitted=false,lastSystemMode=null,customChosen=new Set(),photoBusy=false,photoQueue=Promise.resolve(),pendingPhotos=0,drawsReady=false;const photos={a:[],b:[]};const agentMode=document.querySelector('meta[name="mingli-intake-mode"]')?.content==='agent';
const shichen=[['子','23:00–01:00，跨午夜，早晚不确定也可选'],['丑','01:00–03:00'],['寅','03:00–05:00'],['卯','05:00–07:00'],['辰','07:00–09:00'],['巳','09:00–11:00'],['午','11:00–13:00'],['未','13:00–15:00'],['申','15:00–17:00'],['酉','17:00–19:00'],['戌','19:00–21:00'],['亥','21:00–23:00']];
const wellbeingCommon=[
  ['mood','最近整体感受',['轻松平稳','忙碌充实','有些疲惫','心里有点乱']],
  ['stress','有压力时更需要',['独处整理','找人聊聊','先解决具体问题','休息与放松']],
  ['support','眼前更希望得到',['方向更清楚','被理解','具体建议','梳理选项']]
];
const wellbeingTopics={
  overview:['综合了解',[
    ['focus','眼前主要关注',['工作学习','关系相处','生活安排','暂时说不清']],
    ['pace','最近生活节奏',['稳定有序','事情较多','时忙时闲','正在调整']],
    ['decisions','重要决定更习惯',['列信息比较','听内心感受','和信任的人商量','先试一小步']],
    ['resources','目前较有帮助的支持',['信任的人','可安排的时间','已有的经验','还在寻找']],
    ['changes','对生活变化的期待',['愿意主动尝试','想先了解清楚','想保持稳定','视情况而定']],
    ['clarify','最想先梳理的事',['自己的需要','当前的困难','可行的选择','下一步行动']],
    ['start','愿意先做的一步',['记录想法','找人沟通','尝试小调整','先留点时间']]
  ]],
  personality:['个人特点',[
    ['energy','独处和相处之后',['独处更有精神','相处更有精神','两者都需要','看当时状态']],
    ['expression','表达真实想法时',['通常能说清楚','先想一想再说','需要熟悉的人','还在练习表达']],
    ['response','收到不同意见时',['先听具体理由','先整理感受','找例子核对','需要缓一缓']],
    ['task','面对新任务习惯',['先列计划','边做边调整','先找示范','与人讨论后做']],
    ['boundary','安排自己的边界',['比较能说明','容易先答应','会慢慢调整','还不太清楚']],
    ['strength','自己较认可的长处',['耐心细致','主动推进','理解他人','灵活应变']],
    ['understand','最想认识自己的哪面',['做事方式','情绪需要','相处习惯','选择标准']]
  ]],
  career:['职业方向',[
    ['stage','目前职业探索阶段',['刚开始了解','已有几个方向','想调整现有方向','暂时先做准备']],
    ['work','更想尝试的工作内容',['分析解决问题','表达创作','沟通协作','组织执行']],
    ['setting','较喜欢的工作环境',['职责清楚','自主空间大','团队交流多','节奏较稳定']],
    ['priority','职业选择先看什么',['兴趣契合','收入保障','成长机会','生活平衡']],
    ['experience','对目标方向的了解',['有实际经历','做过一些了解','主要来自想象','还需要探索']],
    ['limit','眼前较受限的条件',['信息不够','技能需补充','时间安排','尚未发现限制']],
    ['explore','愿意怎样探索方向',['访谈从业者','做小项目','学习入门内容','比较岗位要求']]
  ]],
  'job-change':['换工作',[
    ['stage','对换工作的想法',['只是想了解','正在比较机会','已有具体选择','暂不打算换']],
    ['reason','如果换工作最想改善',['工作内容','收入待遇','相处或管理方式','时间与生活安排']],
    ['certainty','对新机会知道多少',['条件比较清楚','还有关键问题','刚开始收集信息','目前没有具体机会']],
    ['reserve','转变前更想准备',['资金缓冲','能力或作品','机会与联系人','交接和时间安排']],
    ['risk','最担心哪种不确定',['收入变化','岗位不合适','新环境适应','影响现有安排']],
    ['criteria','比较机会更看重',['长期方向','眼前条件','团队与合作','稳定程度']],
    ['step','下一步较适合做什么',['核实职位信息','梳理去留理由','补齐准备','先观察现状']]
  ]],
  promotion:['晋升发展',[
    ['goal','希望获得哪种发展',['能力更扎实','承担更多责任','获得认可与回报','先理清发展方向']],
    ['role','对职责期待的了解',['比较清楚','只了解一部分','还没明确讨论','目前不适用']],
    ['evidence','已有成果怎样整理',['有具体记录','想起来能列举','还没整理过','需要先积累']],
    ['communication','表达发展期待时',['愿意直接沟通','想准备好再谈','需要适合的时机','还不确定怎么说']],
    ['challenge','目前较想补足',['专业能力','协作沟通','统筹推进','展示成果']],
    ['load','对增加责任的感受',['愿意尝试','需要资源支持','想先稳住现有工作','还要权衡']],
    ['supporting','发展中最想获得',['具体反馈','学习机会','清楚的评价标准','合理的时间资源']]
  ]],
  finances:['财务收支',[
    ['clarity','对近期收支了解多少',['有记录较清楚','大致知道','偶尔会梳理','还没有整理']],
    ['spending','日常花费更像哪种',['按计划安排','先满足当下需要','遇事再调整','每月差异较大']],
    ['concern','目前最想改善的部分',['开支更清楚','留出储备','减少收支压力','协调长期目标']],
    ['buffer','想到意外开支时',['已有一些安排','正在准备','需要重新梳理','暂时不想回答']],
    ['decision','较大支出前通常',['提前比较','先问是否需要','和相关的人商量','看当时条件']],
    ['balance','较难平衡的需求',['日常与储备','个人与家庭','当下与长期','目前较能平衡']],
    ['action','愿意先做的收支调整',['记一段时间账','整理固定开支','确定储备目标','讨论共同开支']]
  ]],
  income:['收入回报',[
    ['expectation','最想改善哪种回报',['收入水平','收入稳定性','付出与回报匹配','成长与认可']],
    ['effort','对当前投入的感受',['较为匹配','投入有些过多','想调整投入方向','目前还说不清']],
    ['value','较想积累的能力',['专业深度','沟通与协作','解决实际问题','展示成果']],
    ['negotiation','谈论合理回报时',['能说明理由','想先整理依据','不太容易开口','目前没有相关情境']],
    ['path','更愿意探索的方式',['提升现有能力','承担合适任务','了解外部机会','先整理自身条件']],
    ['cost','增加收入时更想保留',['休息时间','稳定安排','自主空间','关系与陪伴']],
    ['measure','怎样判断投入值得',['实际收入变化','能力有所积累','选择机会增加','生活状态更合适']]
  ]],
  dating:['单身感情',[
    ['stage','目前对认识他人的意愿',['愿意主动认识','顺其自然接触','想先照顾自己','还没有明确想法']],
    ['need','期待关系带来什么',['理解与交流','稳定陪伴','共同体验','相互支持成长']],
    ['meeting','较舒服的认识方式',['朋友或熟人介绍','共同兴趣活动','自然日常接触','暂时不想安排']],
    ['pace','了解新对象的节奏',['慢慢熟悉','愿意主动推进','边接触边看','需要更多安全感']],
    ['signals','更想先了解对方',['相处是否舒服','价值与生活方式','沟通是否真诚','彼此的期待']],
    ['boundary','新关系中想保留',['个人时间','原有生活节奏','自己的决定空间','循序渐进的节奏']],
    ['obstacle','认识他人时较难的是',['机会较少','不知怎样开始','判断是否适合','目前没有明显困难']]
  ]],
  relationship:['恋爱相处',[
    ['situation','目前想谈的关系情境',['正在了解彼此','已有较稳定关系','正在经历分歧','只是提前了解']],
    ['closeness','较期待怎样相处',['更多陪伴','更深入交流','更多彼此空间','共同做一些事']],
    ['needs','表达需求时通常',['直接说明','先观察再表达','希望对方能察觉','需要练习说清楚']],
    ['conflict','遇到分歧更希望',['当时说开','先各自冷静','约好再讨论','先解决具体问题']],
    ['difference','较想讨论的差异',['生活节奏','沟通习惯','关系期待','目前没有明确差异']],
    ['care','更容易感受到关心的是',['认真倾听','实际行动','稳定联系','尊重自己的选择']],
    ['next','希望先改善什么',['表达更清楚','理解彼此需要','协商相处安排','弄清是否适合']]
  ]],
  marriage:['婚恋规划',[
    ['stage','对长期关系规划的状态',['刚开始思考','已有部分讨论','面对具体决定','暂时只想了解']],
    ['agreement','更想先讨论什么',['未来生活方式','承诺与期待','经济和日常分工','双方家庭边界']],
    ['timeframe','对推进节奏的期待',['希望慢慢确认','想有清楚计划','取决于实际条件','还没形成期待']],
    ['daily','对共同生活最看重',['彼此尊重','稳定合作','保留个人空间','遇事能商量']],
    ['difference','出现计划差异时',['寻找共同目标','比较现实条件','给彼此思考时间','还需了解对方想法']],
    ['readiness','较想先准备的部分',['沟通与协商','生活和财务安排','认识彼此需要','目前不适用']],
    ['decision','做长期决定前更需要',['双方明确意愿','更完整的信息','一段实际相处','可信赖的支持']]
  ]],
  family:['家庭沟通',[
    ['conversation','最想和家人聊的事',['日常关心','不同意见','生活安排','个人边界']],
    ['frequency','目前沟通的感受',['大多能交流','联系较少','容易话不投机','情况比较复杂']],
    ['expression','表达关心较习惯',['直接说出来','做实际的事','保持联系','陪伴或倾听']],
    ['disagreement','意见不同时更需要',['先被认真听见','把具体问题说清','一些冷静空间','共同寻找做法']],
    ['boundary','对家人参与的期待',['多一些支持','保持适当距离','重要事情再商量','视不同事情而定']],
    ['burden','家庭相处里较累的是',['担心彼此感受','需要承担的事情','解释自己的选择','目前没有明显负担']],
    ['step','愿意先尝试哪种沟通',['找轻松时机聊','写清自己的需要','商量具体安排','先听对方怎么想']]
  ]],
  parenting:['亲子相处',[
    ['situation','这次亲子话题的情境',['想了解与父母相处','想了解与孩子相处','为未来做准备','暂时不便说明']],
    ['need','亲子交流更希望得到',['被认真倾听','更清楚的边界','一起解决问题','更多轻松陪伴']],
    ['parenting-topic','较想讨论的话题',['日常安排','学习或成长','情绪与表达','自主和责任']],
    ['difference','想法不同时更愿意',['先理解原因','说清自己的需要','商量可行规则','缓一缓再交流']],
    ['company','较适合的陪伴方式',['共同做件小事','聊聊最近经历','各自做事但在一起','按彼此需要安排']],
    ['expectation','对彼此期待更想调整',['减少催促或比较','说明具体需要','保留尝试空间','先了解真实想法']],
    ['resource','目前较需要的支持',['沟通方法','时间与分工','可信赖的人协助','先梳理具体情况']]
  ]],
  cooperation:['合作伙伴',[
    ['stage','合作目前处于哪一步',['了解可能性','准备开始','已经在合作','正在调整或结束']],
    ['fit','选择伙伴更看重',['能力互补','沟通可信','目标一致','做事节奏合适']],
    ['roles','对彼此分工的了解',['已经说清楚','大致有共识','还有模糊之处','暂时没有具体合作']],
    ['trust','建立信任更需要',['兑现小承诺','公开必要信息','实际一起做事','遇事能坦诚沟通']],
    ['conflict','分歧时更想怎样处理',['依据约定讨论','核实具体事实','共同找折中方案','先暂停再评估']],
    ['cost','合作中更担心的投入',['时间精力','资金或资源','职责不清','关系受到影响']],
    ['agreement','开始或继续前想确认',['目标与分工','投入与回报','决策和沟通方式','退出或调整的安排']]
  ]],
  learning:['学习深造',[
    ['goal','目前学习更为了什么',['满足兴趣','解决实际需要','准备考试或升学','探索新的方向']],
    ['method','较适合自己的学习方式',['看资料整理','动手练习','听讲后讨论','有反馈的任务']],
    ['time','目前可安排的学习时间',['比较固定','零散但可安排','暂时较少','还没认真规划']],
    ['obstacle','学习中较容易卡在哪里',['不知道从哪开始','难以持续','理解了但难应用','资料选择太多']],
    ['learning-feedback','哪种反馈更有帮助',['看到具体进步','有人解答疑问','完成实际任务','及时知道问题']],
    ['tradeoff','进一步学习更需权衡',['时间安排','费用投入','现有工作或生活','目标是否清楚']],
    ['step','愿意先试的学习安排',['确定一个小目标','找一份入门材料','做一次练习','安排固定时段']]
  ]],
  moving:['居住搬迁',[
    ['stage','居住调整目前处于',['只是想了解','正在比较地点','已有具体选择','暂时不准备改变']],
    ['priority','居住环境更看重',['便利与通勤','安静舒适','身边支持','成本与空间']],
    ['reason','如果改变最想改善',['日常生活体验','工作或学习机会','与重要的人相处','支出或居住条件']],
    ['information','对新地点了解多少',['有实际生活体验','了解过一些条件','信息还比较零散','尚无具体地点']],
    ['adapt','适应新环境更需要',['熟悉的人支持','清楚的生活安排','足够的缓冲时间','逐步探索的空间']],
    ['cost','搬迁前更需权衡',['费用和预算','通勤与时间','关系和照顾安排','现有生活的稳定']],
    ['step','愿意先核实什么',['实际生活成本','工作学习条件','交通与周边环境','支持与过渡安排']]
  ]],
  priorities:['近期重点',[
    ['list','眼前的事情有多清楚',['重点比较明确','几件事同时进行','需要先列一列','暂时还说不清']],
    ['urgent','较想先处理哪类事情',['有明确期限的事','影响日常状态的事','重要关系中的事','长期拖着的事']],
    ['capacity','近期精力安排更像',['有余力推进','刚好应付现有事','需要适当减量','状态有所波动']],
    ['choice','筛选重点更看重',['实际影响','是否有期限','自己的真实需要','手头可用资源']],
    ['barrier','开始行动较缺什么',['方向与信息','时间或精力','具体步骤','支持与配合']],
    ['reduce','哪些事情可以先调整',['降低完成标准','减少不必要安排','请人协助分担','暂时还需梳理']],
    ['step','近期愿意先做什么',['完成一个小任务','约一次必要沟通','留出整理时间','先补足休息']]
  ]]
};
let wellbeingTopic='overview';const wellbeingDrafts={a:{},b:{}};
function wellbeingQuestions(topic=wellbeingTopic){return [...wellbeingCommon,...wellbeingTopics[topic][1]];}
function wellbeingFields(p,topic=wellbeingTopic){return wellbeingQuestions(topic).map(([id,label,options])=>`<label>${label}<select id="${p}-wellbeing-${id}" data-wellbeing="${p}"><option value="">暂不选择</option>${options.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('')}</select></label>`).join('');}
function readWellbeing(p){
  return Object.fromEntries(wellbeingQuestions().flatMap(([id,,options])=>{const value=fieldValue(p+'-wellbeing-'+id);if(value&&!options.includes(value))throw Error('请重新选择心理与近况的选项，或清除后跳过。');return value?[[id,value]]:[];}));
}
function switchWellbeing(topic){
  if(!Object.prototype.hasOwnProperty.call(wellbeingTopics,topic)||topic===wellbeingTopic)return;
  for(const p of ['a','b'])wellbeingDrafts[p][wellbeingTopic]=readWellbeing(p);
  wellbeingTopic=topic;
  for(const p of ['a','b']){
    $(p+'-wellbeing-fields').innerHTML=wellbeingFields(p);
    const saved=wellbeingDrafts[p][topic]||{};for(const [id]of wellbeingQuestions())$(p+'-wellbeing-'+id).value=saved[id]||'';
    $(p+'-wellbeing-topic').value=topic;$(p+'-wellbeing-current').textContent=tr('当前：{topic}',{topic:tr(wellbeingTopics[topic][0])});$(p+'-wellbeing-feedback').textContent='';
  }
}

function personFields(i) {
  const p=i===0?'a':'b', title=i===0?'你的资料':'另一人的资料';
  const photoInputs=[['palm_left','左手掌','掌心朝上，手指自然伸开'],['palm_right','右手掌','拍清整个手掌，避免反光'],['portrait','面部照片','正面、光线均匀，不用美颜']];
  return `<section class="section person" id="person-${p}" ${i?'hidden':''}>
    <div class="section-head"><h2>${title}</h2></div>
    <div class="fields two">
      <div><label>姓名或称呼 <span class="req">*</span><input id="${p}-name" maxlength="80" autocomplete="off" placeholder="真实姓名或你喜欢的称呼" required></label>
        <label class="check name-consent"><input id="${p}-analyze-name" type="checkbox">这是真实姓名，也想了解姓名分析</label>
        <div id="${p}-name-review" class="name-review" hidden><p class="hint" id="${p}-name-preview" data-i18n-ignore aria-live="polite"></p>
          <label>姓名分析方式<select id="${p}-name-mode"><option value="chinese">中文姓名（字形与笔画）</option><option value="international">国际姓名（原文与可选拉丁拼写）</option></select></label>
          <p class="hint">按姓名实际文字选择；日文汉字等也可以选国际姓名。不会自动音译。</p>
          <details id="${p}-name-chinese"><summary>识别的姓氏不对？</summary><label>你的姓氏<input id="${p}-surname-confirm" maxlength="2" placeholder="只在识别错误时填写，例如：欧阳"></label></details>
          <div id="${p}-name-international" hidden><label>拉丁字母拼写（选填）<input id="${p}-name-latin" maxlength="160" placeholder="只填写本人使用的拼写，不自动音译。"><span class="hint">使用英文字母、空格、直撇号或连字符；不确定就留空。</span></label><label>姓名读音（选填）<input id="${p}-name-pronunciation" maxlength="240"></label></div>
        </div>
      </div>
      <label>出生日期 <span class="req" id="${p}-birth-required">*</span><input type="date" id="${p}-date" required></label>
      <label>你填写的是哪种生日？<select id="${p}-calendar"><option value="solar">阳历／公历（身份证常用）</option><option value="lunar">阴历／农历（家里说的生日）</option></select></label>
      <label>出生地点 <span class="req" id="${p}-place-required">*</span><input id="${p}-birthplace" maxlength="200" placeholder="例如：杭州市西湖区，浙江省；国外写国家和城市" required><span class="hint">写城市或区县即可，不需要门牌号；坐标和时区由 AI 查询。</span></label>
      <label>出生时间知道多少？<select id="${p}-time-kind"><option value="unknown">不知道，继续填写</option><option value="exact">知道具体几点几分</option><option value="shichen">只知道时辰（两小时一段）</option></select></label>
      <label>性别 <span class="hint">选填，部分传统排盘会用到</span><select id="${p}-gender"><option value="">暂不提供</option><option value="male">男</option><option value="female">女</option></select></label>
      <label id="${p}-time-field" hidden>具体出生时间<input type="time" id="${p}-time"><span class="hint">填写出生地当时的当地时间，不需要换算。</span></label>
      <label id="${p}-shichen-field" hidden>知道的是哪个时辰？<select id="${p}-shichen"><option value="">请选择知道的时辰</option>${shichen.map(([name,hours])=>`<option value="${name}">${name}时（${hours}）</option>`).join('')}</select><span class="hint">只保留这段时间，不替你填写具体分钟。子时跨午夜，会保留日期边界的不确定。</span></label>
    </div>
    <label class="check leap-row" id="${p}-leap-row" hidden><input type="checkbox" id="${p}-leap">家人明确说是农历闰月</label>
    <div class="details dream-section">
      <label>梦境描述 <span class="heading-hint">选填</span><textarea id="${p}-dream" rows="3" maxlength="4000" placeholder="梦见了什么？写下人物、场景、经过，以及醒来后的感受。"></textarea></label>
      <p class="hint">填写梦境即可做周公解梦，不需要出生日期或地点。</p>
    </div>
    <div class="photo-section">
      <h3>手掌与面部照片 <span class="heading-hint">选填</span></h3>
      <p class="hint">选好照片后就会添加。没有照片也可以继续，不需要自己描述掌纹或面部特征。</p>
      <div class="photo-inputs">${photoInputs.map(([kind,label,hint])=>`<label class="photo-upload">${label}<span class="hint">${hint}</span><input id="${p}-photo-${kind}" type="file" data-photo-file="${p}" data-photo-kind="${kind}" accept="image/png,image/jpeg"></label>`).join('')}</div>
      <p class="hint">支持 JPG、PNG，单张最多 6 MB。照片默认只用于本次查看，不放进报告；最多 12 张、合计 30 MB。</p>
      <details class="details"><summary>还有其他相关图片？<span>选填</span></summary><div class="fields two">
        <label>图片内容<select id="${p}-photo-kind"><option value="room">房间照片</option><option value="floorplan">房屋平面图</option><option value="chart">已有排盘或其他图表</option><option value="palm_unknown">暂时分不清左右的手掌</option><option value="other">其他相关图片</option></select></label>
        <label>添加图片<input type="file" id="${p}-photo-file" data-photo-file="${p}" accept="image/png,image/jpeg"></label>
      </div></details>
      <div class="photo-list" id="${p}-photo-list" aria-live="polite"></div><p class="feedback" id="${p}-photo-feedback" aria-live="polite"></p>
    </div>
    <details class="details wellbeing"><summary>心理与近况（选填）</summary>
      <p class="hint">按这个人的自述选择最接近的感受和偏好，不知道就留空。每组10题，可只答几题或全部跳过。切换主题会保留已选项，提交只包含当前主题。</p>
      <label>想聊哪一方面？<select id="${p}-wellbeing-topic" data-wellbeing-topic="${p}">${Object.entries(wellbeingTopics).map(([id,[label]])=>`<option value="${id}">${label}</option>`).join('')}</select></label>
      <p class="hint" id="${p}-wellbeing-current" data-i18n-ignore>当前：综合了解</p>
      <div class="fields two wellbeing-fields" id="${p}-wellbeing-fields">${wellbeingFields(p)}</div>
      <button type="button" class="wellbeing-clear" data-clear-wellbeing="${p}">清除当前组选择</button>
      <p class="hint wellbeing-feedback" id="${p}-wellbeing-feedback" role="status" aria-live="polite"></p>
    </details>
    <details class="details"><summary>关于这个人，还有想补充的吗？<span>选填</span></summary><label>补充说明<textarea id="${p}-notes" rows="2" maxlength="2000" placeholder="例如：只记得傍晚出生。用自己的话说即可，不确定的地方也可以写。"></textarea></label></details>
  </section>`;
}
$('people').innerHTML=personFields(0)+personFields(1);
function drawActive(){return systemMode()==='all'?'all':systemMode()==='custom'?selectedSystems():[];}

function updateDraws(){if(drawsReady)window.MingxueDraws?.update(drawActive(),{pair:mode()==='pair',question:fieldValue('question')});}
function mode(){return document.querySelector('input[name="mode"]:checked').value;}
function systemMode(){return document.querySelector('input[name="systems-mode"]:checked').value;}
function selectedSystems(){return [...document.querySelectorAll('#system-list input:checked')].map(e=>e.value);}
const timedSystems=new Set(['meihua','iching','qimen','liuren','jinkoujue','xiaoliuren','taiyi','electional','horary']);
function birthOptional(p){
  if(fieldValue(p+'-dream'))return true;
  const chosen=selectedSystems();
  return systemMode()==='custom'&&chosen.includes('meihua')&&chosen.every(id=>['meihua','dream'].includes(id));
}
function needsCast(){
  if(systemMode()==='custom')return selectedSystems().some(id=>timedSystems.has(id));
  const people=mode()==='pair'?['a','b']:['a'];
  return !!fieldValue('question')&&!people.every(p=>fieldValue(p+'-dream')&&!fieldValue(p+'-date'));
}
function updateBirthRequirements(p){
  const optional=birthOptional(p),date=!!fieldValue(p+'-date');
  $(p+'-date').required=!optional;$(p+'-birthplace').required=!optional||date;
  $(p+'-birth-required').hidden=optional;$(p+'-place-required').hidden=optional&&!date;
}
function updateCastFields(){
  const needed=needsCast();$('question-place').hidden=!needed;
  $('cast-place').disabled=!needed||$('cast-same-birthplace').checked;
  $('cast-past-field').hidden=fieldValue('cast-when')!=='past';
}
const compoundSurnames=new Set('欧阳 司马 上官 诸葛 夏侯 皇甫 尉迟 公羊 澹台 公冶 宗政 濮阳 淳于 单于 太叔 申屠 公孙 仲孙 轩辕 令狐 钟离 宇文 长孙 慕容 司徒 司空 亓官 司寇 子车 端木 巫马 公西 颛孙 壤驷 公良 漆雕 乐正 宰父 谷梁 拓跋 夹谷 南宫 东郭 西门 梁丘 左丘 东门 百里 呼延 万俟 赫连 独孤 闻人 第五'.split(' '));
function namingFor(p){
  if(!$(p+'-analyze-name').checked)return null;
  const full=fieldValue(p+'-name'), override=fieldValue(p+'-surname-confirm');
  if(!nameModesInitialized.has(p)){$(p+'-name-mode').value=/^\p{Script=Han}{2,4}$/u.test(full)?'chinese':'international';nameModesInitialized.add(p);}
  if(fieldValue(p+'-name-mode')==='international'){
    if(!full)throw Error('请填写你希望分析的姓名原文。');
    const name={mode:'international',full_name:full},latin=fieldValue(p+'-name-latin'),pronunciation=fieldValue(p+'-name-pronunciation');
    if(latin&&(!/^[A-Za-z '\-]+$/.test(latin)||!/[A-Za-z]/.test(latin)))throw Error('拉丁拼写只接受英文字母、空格、直撇号和连字符。');
    if(latin)name.latin_name=latin;if(pronunciation)name.pronunciation=pronunciation;return name;
  }
  if(!/^\p{Script=Han}{2,4}$/u.test(full))throw Error('姓名分析需要二到四个汉字的真实姓名；如果填的是昵称，可以取消姓名分析。');
  const surname=override||(compoundSurnames.has(full.slice(0,2))?full.slice(0,2):full.slice(0,1)),given=full.slice(surname.length);
  if(!full.startsWith(surname)||!/^\p{Script=Han}{1,2}$/u.test(surname)||!/^\p{Script=Han}{1,2}$/u.test(given))throw Error('请在姓名下方确认一下你的姓氏；其他资料不用重填。');
  return {surname,given};
}
function updateName(p){
  const enabled=$(p+'-analyze-name').checked;
  $(p+'-name-review').hidden=!enabled;
  if(!enabled)return;
  try{const n=namingFor(p),international=n.mode==='international';$(p+'-name-chinese').hidden=international;$(p+'-name-international').hidden=!international;$(p+'-name-preview').textContent=international?tr('保留姓名原文；拉丁拼写和读音只使用你明确填写的内容。'):tr('已识别：姓「{surname}」，名「{given}」。笔画会自动查字库，不需要手算。',{surname:n.surname,given:n.given});}
  catch(e){$(p+'-name-preview').textContent=tr(e.message);}
}
function update(){
  const pair=mode()==='pair';
  $('person-b').hidden=!pair;
  $('person-b').querySelectorAll('input,select,textarea').forEach(el=>el.disabled=!pair);
  $('relationship-field').hidden=!pair;$('relationship').disabled=!pair;
  for(const p of ['a','b']){
    const kind=fieldValue(p+'-time-kind'),active=p==='a'||pair,lunar=fieldValue(p+'-calendar')==='lunar';
    $(p+'-time-field').hidden=kind!=='exact';$(p+'-time').disabled=!active||kind!=='exact';
    $(p+'-shichen-field').hidden=kind!=='shichen';$(p+'-shichen').disabled=!active||kind!=='shichen';$(p+'-leap-row').hidden=!lunar;
    const date=$(p+'-date');if(date.type!==(lunar?'text':'date')){const prior=date.value;date.type=lunar?'text':'date';date.placeholder=lunar?'例如 1995-08-15':'';date.value=prior;}
    updateName(p);
  }
  const current=systemMode(),custom=current==='custom',boxes=[...document.querySelectorAll('#system-list input')];
  if(lastSystemMode==='custom'&&!custom)customChosen=new Set(selectedSystems());
  if(custom&&lastSystemMode!==null&&lastSystemMode!=='custom')boxes.forEach(e=>e.checked=customChosen.has(e.value));
  if(current==='all')boxes.forEach(e=>e.checked=true);if(current==='auto')boxes.forEach(e=>e.checked=false);
  boxes.forEach(e=>e.disabled=!custom);if(custom)customChosen=new Set(selectedSystems());lastSystemMode=current;
  $('system-list').hidden=!custom;
  for(const p of ['a','b'])updateBirthRequirements(p);
  updateCastFields();
  updateDraws();
}
function drawSystems(){
  const grouped=new Map();for(const s of systems){const group=s.category||'其他';if(!grouped.has(group))grouped.set(group,[]);grouped.get(group).push(s);}
  $('system-list').innerHTML=[...grouped].map(([group,list])=>`<div class="system-group"><h4>${esc(group)}</h4><div class="system-options">${list.map(s=>`<label class="system-choice" title="${esc(s.summary)}"><input type="checkbox" value="${esc(s.id)}">${esc(s.name)}</label>`).join('')}</div></div>`).join('');
  update();
}
function fieldValue(id){return $(id).value.trim();}
const questionPresets={
  overview:'我想综合了解自己的性格特点、做事习惯，以及工作、财务、感情和家庭中值得留意的方向。请结合我实际提供的资料分析，不确定的地方保留。',
  personality:'我有哪些比较稳定的性格和做事特点？面对压力、与人沟通和做选择时，通常有什么优势，又有哪些容易忽略的地方？',
  career:'从我的特点和做事习惯来看，哪些工作方向、工作环境或职责可能更适合我？我可以怎样结合自己的经历进一步判断？',
  'job-change':'如果考虑换工作，我可以先梳理哪些需求，怎样比较现有安排与新的机会？请说明适合留意的地方和需要我补充的信息。',
  promotion:'如果希望在工作中获得成长或承担更多责任，我可以怎样发挥优势、补足短板，并和相关的人沟通自己的期待？',
  finances:'我想了解自己在赚钱、花钱和安排收支方面可能有哪些习惯。怎样更清楚地分配日常开支、储备和长期目标？',
  income:'我想了解自己的付出与收入回报之间可以怎样协调。哪些能力值得积累，哪些期待和选择需要结合实际条件再判断？',
  dating:'如果处于单身阶段，我可以怎样认识自己的感情需求、扩大认识他人的机会，并判断一段关系是否适合继续了解？',
  relationship:'如果正在恋爱或了解一段关系，我可以怎样理解双方的沟通方式、表达需求和处理分歧？请只根据我提供的实际情况分析。',
  marriage:'在考虑长期关系或婚姻安排时，我可以先想清楚哪些需求，怎样讨论生活分工、承诺与未来计划？没有提供的关系情况请不要假定。',
  family:'我想了解与家人沟通时自己的习惯和容易卡住的地方。怎样表达关心、讨论不同意见，同时保留彼此需要的空间？',
  parenting:'如果涉及亲子相处，我可以怎样理解沟通、陪伴和边界上的需要？请根据实际提供的家庭情况分析，不假定我已经有孩子。',
  cooperation:'如果考虑与人合作，我可以怎样判断分工、沟通和互相信任的方式？在开始或继续合作前，有哪些事情适合说清楚？',
  learning:'从我的特点和学习习惯来看，怎样安排学习、考试准备或进一步深造可能更适合我？我可以怎样结合实际目标选择投入的方向？',
  moving:'如果考虑搬家、换城市或调整居住环境，我可以先梳理哪些需求，怎样比较生活安排、工作机会和身边支持，再决定下一步？',
  priorities:'我想梳理近期最值得关注的事情。结合我提供的资料和问题，哪些方面适合先行动，哪些方面可以继续观察和补充信息？'
};
$('question-presets').addEventListener('click',event=>{
  const button=event.target.closest('[data-question-preset]'),source=button&&questionPresets[button.dataset.questionPreset];
  if(!source)return;const text=tr(source);
  switchWellbeing(button.dataset.questionPreset);
  const input=$('question'),feedback=$('question-preset-feedback');
  if(['zh-CN','en','ja','ko'].some(language=>input.value.includes(tr(source,undefined,language)))){feedback.textContent='这个问题已经在下方，可以继续修改。';input.focus();return;}
  const next=input.value+(input.value?'\n\n':'')+text;
  if(next.length>input.maxLength){feedback.textContent='问题框快写满了，请先整理已有内容，再加入这个问题。';return;}
  input.value=next;input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
  feedback.textContent='问题已加入，原来写的内容已保留，可以继续修改。';
});

function collectPerson(p){
  const name=fieldValue(p+'-name'),date=fieldValue(p+'-date'),birthplace=fieldValue(p+'-birthplace'),dream=fieldValue(p+'-dream'),label=p==='a'?'第一人':'第二人';
  if(!name||!birthOptional(p)&&(!date||!birthplace))throw Error(`${label}请填写姓名或称呼、出生日期和出生地点。`);
  if(dream.length>4000)throw Error('梦境描述请控制在4000字以内。');
  let birth=null;
  if(date){
    if(!birthplace)throw Error(`${label}请填写出生地点，或留空出生日期。`);
    const calendar=fieldValue(p+'-calendar'),match=/^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
    if(!match||Number(match[1])<1583||Number(match[2])<1||Number(match[2])>12||Number(match[3])<1||Number(match[3])>(calendar==='lunar'?30:31))throw Error('请核对出生日期，按年、月、日填写。');
    birth={date,calendar,time:null};const kind=fieldValue(p+'-time-kind'),gender=fieldValue(p+'-gender');
    if(kind==='exact'){const time=fieldValue(p+'-time');if(!/^([01]\d|2[0-3]):[0-5]\d$/.test(time))throw Error(`${label}请选择具体出生时间，或者改成“不知道”。`);birth.time=time;}
    else if(kind==='shichen'){const value=fieldValue(p+'-shichen');if(!shichen.some(([name])=>name===value))throw Error(`${label}请选择知道的时辰，或者改成“不知道”。`);birth.shichen=value;}
    else if(kind!=='unknown')throw Error('请选择出生时间知道多少。');
    if(gender)birth.gender=gender;if(calendar==='lunar')birth.leap=$(p+'-leap').checked;
  }
  const selectedWellbeing=readWellbeing(p);wellbeingDrafts[p][wellbeingTopic]=selectedWellbeing;
  const selfReported=wellbeingQuestions().flatMap(([id,label])=>{
    const value=selectedWellbeing[id];
    return value?[tr(label)+'：'+tr(value)]:[];
  });
  const person={name},notes=[fieldValue(p+'-notes'),selfReported.length?tr('本人自述（心理与近况｜{topic}）',{topic:tr(wellbeingTopics[wellbeingTopic][0])})+'\n'+selfReported.join('\n'):''].filter(Boolean).join('\n\n');if(notes)person.notes=notes;
  const out={person,birth},naming=namingFor(p);if(birthplace)out.birthplace=birthplace;if(dream)out.dream=dream;if(naming)out.name=naming;
  if(photos[p].length)out.photos=photos[p].map(x=>({...x.ref}));
  return out;
}
function collect(){
  const m=mode(),people=[collectPerson('a')];if(m==='pair')people.push(collectPerson('b'));
  const selected=systemMode()==='all'?'all':systemMode()==='auto'?'auto':selectedSystems();
  if(Array.isArray(selected)&&!selected.length)throw Error('请至少选一项分析内容，或者使用综合分析。');
  const relationship=fieldValue('relationship');if(m==='pair'&&!relationship)throw Error('请选择两个人的关系。');
  const question=fieldValue('question'),preferences={systems:selected,question,depth:'detailed',answers:{},virtual_draws:$('virtual-draws').checked,prepare_engines:false,ui_language:uiLanguage(),language:'auto'};
  if(m==='pair')preferences.relationship=relationship;
  for(const [id,label] of [['answer-background','事情背景'],['answer-uncertainty','补充或不确定说明']]){const value=fieldValue(id);if(value)preferences.answers[label]=value;}
  if(needsCast()){
    const place=$('cast-same-birthplace').checked?people[0].birthplace:fieldValue('cast-place');
    if(!place)throw Error('请写下这次提问所在的城市，或勾选“我现在就在出生地”。');
    preferences.cast_place=place;
    if(fieldValue('cast-when')==='past'){
      const clock=fieldValue('cast-datetime');if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(clock))throw Error('请选择当时的日期和时间，或者使用“现在提问”。');
      preferences.cast={date:clock.slice(0,10),time:clock.slice(11)};
    }else preferences.cast={datetime_utc:new Date().toISOString()};
  }
  return {mode:m,people,preferences};
}
function resultLink(f){const u=new URL(f.url,location.href);if(u.origin!==location.origin||!/^\/(?:api\/)?files\//.test(u.pathname))throw Error('报告地址不是本机文件地址。');return `<div class="result-row"><strong>${esc(f.title||'独立报告')}</strong><div class="result-links"><a href="${esc(u.pathname+u.search)}" target="_blank" rel="noopener">打开报告 ↗</a><a href="${esc(u.pathname+u.search)}" download="${esc(f.filename||'report.html')}">下载 HTML ↓</a></div></div>`;}
const photoLabels={palm_left:'左手掌',palm_right:'右手掌',palm_unknown:'手掌',portrait:'人像',room:'空间照片',floorplan:'平面图',chart:'已有图盘',other:'其他'};
function drawPhotos(person){$(person+'-photo-list').innerHTML=photos[person].map((x,i)=>`<article class="photo-item"><img loading="lazy" decoding="async" width="80" height="80" src="${esc(x.url||(window.photoUrl?window.photoUrl(x.ref.id):'/api/photos/'+encodeURIComponent(x.ref.id)))}" alt="${esc(photoLabels[x.ref.kind]||'图片')}预览"><div><strong>${esc(photoLabels[x.ref.kind]||'图片')}</strong><span>${esc(x.name)}</span><label class="check"><input type="checkbox" data-photo-include="${person}" data-photo-index="${i}" ${x.ref.include_in_report?'checked':''}>保留在报告中</label><button type="button" data-photo-remove="${person}" data-photo-index="${i}">删除图片</button></div></article>`).join('')}
async function photoRequest(url,body){const options={headers:{Authorization:`Bearer ${token}`}};if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}const response=await fetch(url,options);let data;try{data=await response.json()}catch(_){throw Error('图片暂时无法处理，请稍后重试。')}if(!response.ok||data.ok===false||data.status==='error'){const error=data.error||data.message||'图片处理失败。';throw Error(typeof error==='string'?error:(error.message||'图片处理失败。'))}return data}
async function photoList(){const data=await photoRequest('/api/photos');if(!Array.isArray(data.photos))throw Error('暂时无法确认图片，请稍后重试。');return data.photos;}
async function recoverPhoto(person,file,kind){
  if(!window.crypto?.subtle||typeof file.arrayBuffer!=='function')return null;
  try{
    const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),x=>x.toString(16).padStart(2,'0')).join('');
    const item=(await photoList()).find(x=>x.person===person.toUpperCase()&&x.kind===kind&&x.sha256===sha256);
    if(!item||[...photos.a,...photos.b].some(x=>x.ref.id===item.id))return null;
    return {ref:{id:item.id,kind:item.kind,sha256:item.sha256,include_in_report:false}};
  }catch(_){return null;}
}
function readPhoto(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=reader.onabort=()=>reject(Error('无法读取所选图片，请重新选择。'));reader.onload=()=>resolve(String(reader.result).split(',')[1]||'');reader.readAsDataURL(file)})}
function uploadPhoto(person,file,kind,input){
  if(input)input.value='';
  if(!file)return Promise.resolve();
  if(busy||submitted||photoBusy&&!pendingPhotos){$(person+'-photo-feedback').textContent='请等待当前操作完成后重新选择图片。';return Promise.resolve();}
  pendingPhotos++;photoBusy=true;$(person+'-photo-feedback').textContent='正在添加图片，请稍候…';
  photoQueue=photoQueue.then(async()=>{
    let url='';
    try{
      const mime=file.type||(/\.png$/i.test(file.name)?'image/png':/\.jpe?g$/i.test(file.name)?'image/jpeg':'');
      if(!['image/png','image/jpeg'].includes(mime)||!file.size||file.size>6*1024*1024)throw Error('请选择不超过 6 MB 的 JPG 或 PNG 图片。');
      const all=[...photos.a,...photos.b];if(all.length>=12||all.reduce((n,x)=>n+x.bytes,0)+file.size>30*1024*1024)throw Error('最多 12 张、合计 30 MB。');
      url=URL.createObjectURL(file);
      const body={person:person.toUpperCase(),kind,name:file.name,mime,data_base64:await readPhoto(file),include_in_report:false};
      let result;try{result=await photoRequest('/api/photos',body);}catch(error){result=await recoverPhoto(person,file,kind);if(!result)throw error;}
      const ref=result.ref;
      if(!ref||typeof ref.id!=='string'||!/^[a-f0-9]{32}$/.test(ref.id)||ref.kind!==kind||typeof ref.sha256!=='string'||!/^[a-f0-9]{64}$/.test(ref.sha256))throw Error('图片暂时无法保存，请重新选择。');
      photos[person].push({ref:{id:ref.id,kind:ref.kind,sha256:ref.sha256,include_in_report:false},name:file.name,bytes:file.size,url});url='';drawPhotos(person);
      $(person+'-photo-feedback').textContent='图片已添加；如需保留在报告中，请单独勾选。';
    }catch(e){$(person+'-photo-feedback').textContent=friendly(e.message,'图片暂时无法添加，请重新选择后重试。');}
    finally{if(url)URL.revokeObjectURL(url);pendingPhotos--;if(!pendingPhotos)photoBusy=false;}
  });
  return photoQueue;
}
async function removePhoto(person,index){const item=photos[person][index];if(!item)return;try{await photoRequest('/api/photos/remove',{id:item.ref.id});}catch(error){let remaining;try{remaining=await photoList();}catch(_){throw error;}if(remaining.some(x=>x.id===item.ref.id))throw error;}photos[person].splice(index,1);if(item.url)URL.revokeObjectURL(item.url);drawPhotos(person)}
$('intake').addEventListener('change',async e=>{const el=e.target;if(/^[ab]-name-mode$/.test(el.id)){const p=el.id[0];nameModesInitialized.add(p);updateName(p);return;}if(el.dataset.wellbeingTopic){switchWellbeing(el.value);return;}if(el.dataset.photoFile){await uploadPhoto(el.dataset.photoFile,el.files?.[0],el.dataset.photoKind||$(el.dataset.photoFile+'-photo-kind').value,el);return}if(el.dataset.photoInclude){const item=photos[el.dataset.photoInclude][Number(el.dataset.photoIndex)];if(item)item.ref.include_in_report=el.checked;return}if(el.name==='mode'||el.name==='systems-mode'||el.matches('#system-list input,#a-calendar,#b-calendar,#a-time-kind,#b-time-kind,#a-analyze-name,#b-analyze-name,#cast-same-birthplace,#cast-when'))update()});
$('intake').addEventListener('click',async e=>{
  const clear=e.target.closest('[data-clear-wellbeing]');
  if(clear&&['a','b'].includes(clear.dataset.clearWellbeing)){
    const p=clear.dataset.clearWellbeing;for(const [id]of wellbeingQuestions())$(p+'-wellbeing-'+id).value='';wellbeingDrafts[p][wellbeingTopic]={};
    $(p+'-wellbeing-feedback').textContent='当前组已清除，可以直接跳过。';return;
  }
  const btn=e.target.closest('[data-photo-remove]');if(!btn||photoBusy||busy||submitted)return;const person=btn.dataset.photoRemove;photoBusy=true;try{await removePhoto(person,Number(btn.dataset.photoIndex));$(person+'-photo-feedback').textContent='图片已删除。'}catch(err){$(person+'-photo-feedback').textContent=friendly(err.message,'图片暂时无法删除，请稍后重试。')}finally{photoBusy=false}
});
function currentRequest(){if(!window.MingxueDraws)throw Error('抽取页面未能打开，请重新进入资料页。');return window.MingxueDraws.apply(collect(),drawActive());}
async function submitCurrent(e){e.preventDefault();if(photoBusy){$('feedback').textContent='请等待图片操作完成后再提交。';return}if(busy||submitted)return;$('feedback').textContent='';try{const data=currentRequest();busy=true;$('submit').disabled=true;$('cancel').disabled=true;$('submit').firstChild.textContent=offlineMode?'正在整理资料包… ':agentMode?'正在提交资料… ':'正在生成报告… ';$('feedback').textContent=offlineMode?'正在准备资料包，照片会一起保存在里面。':agentMode?'正在提交资料，请保持页面打开。':'正在计算并整理报告，所需时间取决于所选体系；请保持页面打开。';const res=await fetch('/api/submit',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:JSON.stringify(data)});let result;try{result=await res.json();}catch(_){throw Error(`提交未成功，请稍后重试。`);}if(!res.ok||result.status==='error'||result.ok===false){const err=result.error||result.message||(Array.isArray(result.warnings)?result.warnings.find(x=>typeof x==='string'&&x.trim()):'')||`请求失败（${res.status}）`;throw Error(typeof err==='object'?(err.message||JSON.stringify(err)):err);}if(result.status==='submitted'){submitted=!offlineMode;$('result-kicker').textContent=offlineMode?'资料包已准备好':'资料已提交';$('result-title').textContent=offlineMode?'把资料包发回对话':'资料已提交';$('result-description').textContent=offlineMode?'资料包已开始下载。把它发回当前对话，AI 会继续查算和分析。':'请回到对话继续。';const pack=window.MingxueDownload;$('result-list').innerHTML=offlineMode&&pack?`<div class="result-links"><button type="button" class="secondary" data-download-current>重新下载资料包</button></div>`:'';$('warnings').innerHTML='';$('results').hidden=false;$('feedback').textContent=offlineMode?'资料包已准备好，请下载后发回对话。':'资料已提交，请回到对话继续。';$('results').scrollIntoView({behavior:'smooth'});return;}if(!Array.isArray(result.files)||!result.files.length)throw Error('报告暂时无法打开，请稍后重试。');$('result-list').innerHTML=result.files.map(resultLink).join('');$('warnings').innerHTML=(result.warnings||[]).filter(w=>typeof w==='string').map(w=>`<p class="hint">${esc(w)}</p>`).join('');$('results').hidden=false;$('feedback').textContent=result.status==='partial'?'报告已生成可呈现的部分。':'报告已生成。';$('results').scrollIntoView({behavior:'smooth'});}catch(error){$('feedback').textContent=friendly(error.message,'未能完成，请检查资料后重试。');}finally{busy=false;$('submit').disabled=submitted;$('cancel').disabled=submitted;$('submit').firstChild.textContent=submitted?(offlineMode?'资料包已准备好 ':'资料已提交 '):offlineMode?'下载资料包 ':agentMode?'提交资料 ':'生成独立报告 ';}}
$('intake').addEventListener('submit',submitCurrent);
$('result-list').addEventListener('click',e=>{if(e.target.closest('[data-download-current]'))return submitCurrent(e);});
window.MingxueIntake=Object.freeze({getRequest:currentRequest,download:()=>submitCurrent({preventDefault(){}})});

$('cancel').addEventListener('click',async()=>{if(!agentMode||busy||submitted||photoBusy)return;busy=true;$('submit').disabled=true;$('cancel').disabled=true;$('feedback').textContent='正在取消…';try{const res=await fetch('/api/cancel',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body:'{}'});let result;try{result=await res.json();}catch(_){throw Error('取消请求未返回可读取的结果。');}if(!res.ok||result.status!=='cancelled')throw Error(typeof result.error==='object'?(result.error.message||'取消失败。'):(result.error||result.message||'取消失败。'));submitted=true;$('result-kicker').textContent='04 / 已取消';$('result-title').textContent='本次填写已取消';$('result-description').textContent='请回到对话继续。';$('result-list').innerHTML='';$('warnings').innerHTML='';$('results').hidden=false;$('feedback').textContent='已取消，请回到对话继续。';$('submit').firstChild.textContent='本次已取消 ';$('results').scrollIntoView({behavior:'smooth'});}catch(error){$('feedback').textContent=friendly(error.message,'未能完成，请检查资料后重试。');}finally{busy=false;$('submit').disabled=submitted;$('cancel').disabled=submitted;}});

if(agentMode){
  $('cancel').hidden=offlineMode;
  $('submit').firstChild.textContent=offlineMode?'下载资料包 ':'提交资料 ';
  $('wait-note').textContent=offlineMode?'下载资料包后发回对话。照片保存在资料包内，地点在分析前联网查询。':'提交后回到对话。地点和姓名笔画会在分析前自动查询。';
  $('guide-last').textContent=offlineMode?'下载资料包，发回对话':'提交后回到对话继续';
}
$('draw-options').addEventListener('toggle',()=>{if(!$('draw-options').open)return;if(!drawsReady&&window.MingxueDraws){window.MingxueDraws.init($('intake-draws'),{backUrl:window.MingxueArt?.card_back?.src||''});drawsReady=true;}updateDraws();});
$('question').addEventListener('input',()=>{updateCastFields();updateDraws();});$('intake').addEventListener('input',e=>{const p=e.target.id?.slice(0,1);if(['a','b'].includes(p)){if(['-name','-surname-confirm','-name-latin','-name-pronunciation'].some(s=>e.target.id===p+s))updateName(p);if(['-dream','-date'].some(s=>e.target.id===p+s)){updateBirthRequirements(p);updateCastFields();}}});update();
$('ui-language').addEventListener('change',()=>window.MingxueI18n?.setLanguage($('ui-language').value));
window.MingxueI18n?.subscribe(language=>{
  $('ui-language').value=language;
  for(const p of ['a','b']){updateName(p);$(p+'-wellbeing-current').textContent=tr('当前：{topic}',{topic:tr(wellbeingTopics[wellbeingTopic][0])});}
});
window.addEventListener('pagehide',event=>{if(event.persisted)return;for(const item of [...photos.a,...photos.b])if(item.url)URL.revokeObjectURL(item.url);});
(async()=>{try{const r=await fetch('/api/catalog',{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);const data=await r.json();systems=Array.isArray(data.systems)?data.systems:[];drawSystems();if(!token&&!offlineMode)$('feedback').textContent='页面已失效，请重新打开资料页。';}catch(e){$('system-list').innerHTML=`<p class="feedback">目录暂时无法打开，请重新进入资料页。</p>`;}})();
})();
