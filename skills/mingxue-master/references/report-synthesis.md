# 证据绑定的综合图文总结

综合总结按主题连接本次实际方法结果，说明相近线索、口径分歧和可行动的下一步，不把多个方法作投票或命运总分。自动层只提供真实完成度和少量可定位字段；叙述由 Agent 阅读当前结果及已应用解读后撰写。

综合默认将个人特点、事业、财运、爱情、家庭和近期重点各自成节详细展开；针对性问题只展开所问主题。每节写清主要判断、真实依据、优势与矛盾、具体情境及可用做法，避免只有一段概括。行动建议须说明适用情境、实际做法和检验标准，同一节的依据标签按本人及方法合并显示，底层完整pointer保持不变。最终默认使用`agent_report deliver`同时给出HTML和实际PDF。

```python
from report_synthesis import synthesis_context, validate_synthesis

context = synthesis_context(records, "A")
overview = validate_synthesis(agent_json, records, "A")

context = synthesis_context(records, "pair", comparison=actual_comparison)
overview = validate_synthesis(pair_agent_json, records, "pair", comparison=actual_comparison)
```

`records` 使用 `agent_report.snapshot` 的记录：`role` 为 a/b，包含 `packed/report/payloads/workspace`，并带当前 `relationship` 背景。`scope` 严格为 `A/B/pair`。模块不读取另一套项目、不调用模型、不重排盘、不抽牌，也不修改传入的 records、comparison 或叙述 JSON。

输入应来自已校验提交摘要的真实 snapshot；本模块不替代存储层的文件完整性检查。缺少逐方法解读时，由 Agent 主流程先阻断最终导出。这里负责本次内容绑定与引用的机械校验。

## 上下文合同

```json
{
  "scope": "A",
  "context_sha256": "64位摘要",
  "subjects": [{"person":"A","name":"示例甲","birth":{},"location":{},"question_hash":"当前问题摘要"}],
  "relationship": "用户选定的关系背景",
  "coverage": [{"person":"A","system":"numerology","title":"数秘","state":"ready","kind":"ready","calculated":true,"reading_status":"applied","result_sha256":"实际提交结果摘要"}],
  "coverage_counts": {"selected":1,"ready":1,"partial":0,"calculated":1,"needs_input":0,"reference":0,"observation":0,"unavailable":0},
  "coverage_note": "计数只表示完成度，不是命运概率或匹配评分。",
  "required_systems": [{"person":"A","system":"numerology","title":"数秘"}],
  "highlights": [{"person":"A","system":"numerology","label":"生命路径归约数","value":8,"pointer":"/life_path/reduction/number","result_sha256":"实际结果摘要"}]
}
```

coverage 从真实 report panels 逐项生成，保留全部选中方法，包括已算、部分、待补、资料、观察及不可用状态。ready/partial 计入已算；未准备引擎、未完成输入、资料入口与观察不会伪装成计算依据。部分姓名结果若已有真实五格、但仍缺读音等条件，可按已有计算部分引用。

`dream` 即使已完成真实古文检索、面板为ready，仍归 `kind=reference`、`calculated=false`；梦境自述、匹配词与古文不计入命盘结果覆盖，也不能当作主题的计算basis。梅花易数 `meihua` 使用自己的实际卦象和体用结果，不能用另一份六爻的结果哈希替代。麻衣仍属于 `face` 的观察，不加入人生预测综合。

highlights 只读取固定白名单的实际字段，例如日主、数秘归约数、本命宿、命宫、太阳星座、卦名、棋课名。字段不存在或为 null 时不补造。value 直接来自其 payload pointer，不从姓名、照片或履历推断特征，也不生成新的健康、人格、命运或匹配指标。

哈希绑定范围包括：

- 所选 scope、人物原始 person/birth/location、当前 question_hash 与关系背景。
- 各选中体系状态、实际 result_sha256、原始 payload 内容摘要、解读状态及当前已应用解读的文字／依据。
- pair 的本次实际 comparison 全文摘要；其 evidence.people 的人物包摘要必须与当前双方 packed 一致。存在 reading_context 时也须与当前双方 question_hash 一致。

不绑定 revision、workspace、result_file 或 reused_from 路径。相同内容不会仅因版本号或移动位置失效。A 的个人上下文不因 B 的内容变化失效。任何出生事实、地点、称呼／说明、问题、关系背景、已应用解读或实际结果变化，均不能套用旧综合。

pair 返回额外 `comparison_sha256`；`required_systems` 为空，因为不强迫把所有个人方法拼成关系结论。双方实际依据仍是必须条件；可从当前可比较方法中精选。

## Agent 叙述协议

根字段必须恰好为下面七项，不能提交自填 coverage、状态、highlights、概率或评分：

```json
{
  "context_sha256": "本次上下文摘要",
  "summary": "围绕本次问题的综合总结，联系主要线索并保留分歧与缺条件。",
  "themes": [{"title":"综合主题","text":"有依据、有限定的主题说明。","basis":[{"person":"A","system":"numerology","pointer":"/life_path","label":"本次真实归约过程"}]}],
  "agreements": [],
  "differences": [],
  "actions": [{"title":"下一步","text":"可由用户选择的具体行动，不保证现实结果。","basis":[{"person":"A","system":"numerology","pointer":"/life_path","label":"本次真实归约过程"}]}],
  "limitations": ["传统符号对照不构成独立预测验证。"]
}
```

- summary 为非空文字，最多 12000 字符；themes 为 1—20 条，actions 为 1—20 条；agreements/differences 可为空，各至多 15 条，不强凑共性或分歧。
- 每条恰好包含 title/text/basis，标题最多 120 字符，文字最多 6000 字符，依据 1—50 条；limitations 为至多 30 项文字，每项最多 2000 字符。整个叙述 JSON 最大 512 KB。
- basis 恰好包含 person/system/pointer/label；角色须在本 scope，体系使用准确 canonical ID，标签为非空文字且最多 300 字符。pointer 相对实际该体系 payload，不是相对报告或 `/results/` 包装；须能真实定位且不是 null。数组不接受负索引或非规范索引。
- 资料、观察、待补或不可用方法可在 summary/limitations 中明确说明，不能被放入 basis 假称已计算。没有实际可算依据时不制造结论。
- 个人综合按生活方面展开，针对性分析按所问主题展开；每个主题仍须有实际相关的多方法结果依据。不要求全部ready/partial方法进入综合，避免为覆盖数量拼接无关内容。required_systems保留为兼容的实际已算清单，不再是强制引用清单。
- pair 的所有叙述合起来必须有 A、B 的结果类计算依据。每条 pair agreements/differences 还必须自身同时引用双方，并涉及至少两个不同 canonical 方法；A 数秘加 B 数秘仍只算一种方法。个人的跨体系共性／分歧每条也要求至少两种方法。
- 不同体系的相近线索仅是所选主题下的叙事对照，不称为独立验证，不投票，不换算婚姻、健康、投资或命运的评分／概率。可没有共性或分歧，尤其只完成一种方法时。

校验返回 `status:"validated"`、当前真实 context 字段与已校验叙述，可作为 UI overview 使用。模块保留文字中的普通字符，所有文本仍必须由 UI escape 后显示。

机械校验不能判定每句话是否与依据语义相符，更不能验证现实预测真伪。模块只对明确的未实现“匹配度／相容度／命运评分”等数值评分句式作窄拒绝，不把普通计算值、角度或百分号本身当作错误。Agent 仍须逐条核读实际依据及限制，避免在有效 pointer 旁写出没有依据的结论。

### 结果引用与口径说明分开计数

引用分类沿 pointer 路径检查，不以 label 自称“结论”决定。纯身份、状态、版本与摘要元字段，例如 `/system`、`/schema_version`、`/status`、`/ok`、`/deck_id`，以及同类深层字段、camelCase 版本名与 hash 字段，直接拒绝作为综合依据。整个方法名不是该方法已得出结论的证据。

输入、规则与协议可用于说明口径，例如 `/input`、`/method`、`/convention`、`/rules`、`/randomness`、`/evidence`、`/source_chart`、种子及层级 scope；它们可以与真实结果共同出现，但不能单独贡献方法覆盖。姓名的原始读音／字义说明、显式笔画及其他未列入结果根的字段也只作支持说明。

只有位于下列实际输出根内、且不经过元字段／输入／口径路径的引用，才能计入“使用了该方法”。结果容器若只包含身份或协议字段，也不计覆盖；计算得到的空动爻／关系集合可保留其真实空结果含义。该规则不机器证明每句话的语义，只阻止拿方法名、原始输入或协议对象充当已算结论。

| 方法 | 可计入覆盖的实际输出根示例 |
| --- | --- |
| 八字 | `pillars`、`details`、`candidates`、`yun` |
| 西占／恒星基础／七政／卜卦占星 | `candidates` 内实际天体、相位、尊贵、主星等；西占／恒星另有 `sun_ranges/sun_sign` |
| 紫微 | `soul_palace/body_palace/chart/natal_mutagens/horoscope` |
| 姓名 | `five_grids/three_talents/characters/candidates/homophone_reminders`；国际姓名实际派生结果 `writing/latin_numerology` |
| 数秘 | `life_path/personal_year/name_expression` |
| 宿曜 | `birth_mansion/daily_mansion/daily_relation/partner_mansion/partner_relation` |
| 周易 | `hexagrams/moving_positions/lines_bottom_to_top/najia/reading/cast_context` 的实际计算部分 |
| 塔罗／雷诺曼 | `cards`；雷诺曼另有实际 `significator` |
| 小六壬／金口诀 | 三位置、最终宫、步骤，或 `four_positions/candidates` 等实际课盘 |
| 太乙 | `chart/nine_palaces` |
| 易林／灵棋 | `oracle`、卦／棋形等实际查辞与结果 |
| 土占 | `shield/house_chart` |
| 黄历 | `records` 内实际日表条目 |

个人主题的多方法依据、pair的双方门槛及每条agreements/differences的方法数，都只统计上述结果类引用。口径引用不会被暗算成第三种方法，也不能用 B 的输入字段替代 B 的实际结果。资料／观察／待补方法仍按前述限制处理。

## 所有方法与独立提问地点

基础请求现在可显式选择 `preferences.systems:"all"`，会规范化为现有 25 个准确 ID；默认 API 的 `auto` 不变。全选只保留所有能力入口，不代表缺条件的方法已算，也不授权虚拟抽样。

`preferences.cast` 可只填成对 latitude/longitude，地点会保留，需提问时刻的方法显示待补。若开始填写任何 date/time/timezone，三项必须完整且钟点明确；不会补造当前时刻、借生日或默认时区。

双人工作流 questionnaire 添加机器字段 `_relationship_context`，使关系背景更正自然改变现有 question_hash，旧个人解读随之失效；其余用户问答原样保留。用户 answers 不允许自填此保留键。单人不添加该机器字段，保留旧调用兼容性。

## 实际验收

`test_report_synthesis.py` 支持 `MINGXUE_TEST_SKILL_ROOT`，也兼容包内或 `Base/package/mingxue-master` 的测试定位。18 项实际测试最终重跑通过，无跳过，16.774 秒：包括旧上下文、生日／地点／称呼／问题／关系／解读变动失效；版本路径不无谓失效；全部已算方法结果引用覆盖；跨人、伪状态、未计算与错误 pointer 拒绝；真实数秘＋宿曜仅引用 system 时拒绝；深层元字段及只含 metadata 的结果容器不计；input/convention-only 无法覆盖；pair 不得用口径字段凑双方或 distinct 方法；窄反评分与普通计算值保留；原始字数上界及超量首尾空格拒绝；all25 无未授权随机；提问地点单独保留；真实双人项目关系更正使旧 personal reading stale。
