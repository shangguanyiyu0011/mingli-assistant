# 一键综合、解释与资料更正

用于用户要求综合分析、保存完整报告，或在已有分析中更正出生资料。按当前问题选择适用体系，不强制运行全部体系；普通概念问答直接回答。

由Agent处理一次性资料表、个人/双人报告时，先用 [Agent工作流](agent-workflow.md)。该层负责重新规划本人派生日期与资料更正；本页保留原生单项目工具及解读补丁格式。

## 从对话到报告

1. 复用本轮已知资料，区分出生、起卦、抽牌、姓名与用事日期。只补确实影响当前问题且无法推断的缺项；未知时间保留未知。不要因中文对话就推断出生时区。
2. 在当前任务的工作目录创建输入JSON和独立项目工作区。工作区必须位于插件、技能、资源与外置缓存之外，不选择这些目录的上级作为项目。项目会保留出生资料、图片副本和历史报告，仅在用户需要存档或完整报告时使用。
3. 用启动器执行下列 `workflow run`。`systems:auto` 自动选择已具备输入的基础体系；特定请求可明确选体系。未明确请求起卦或抽牌时不附送随机结果。缺引擎或输入时保留其它已完成模块。
4. 读取实际 `report_json`、模块结果和相关规则文件。按本次专题整理中文解释，区分计算事实、传统解释与用户自述。每段解释附实际可定位的计算字段、古籍证据卡或模块规则；资料名称与篇章可以保留，不附加人员、账号或无关链接。
5. 将解释与本次 `result_sha256`、`question_hash` 绑定，以 `readings` 补丁执行一次 `workflow update`，交付最新HTML报告及必要摘要。程序只验证依据文件/字段可定位，不替代解释质量判断。尚缺条件的模块明确列出缺项，不编个人结果。

Windows命令示例（从技能目录执行；路径替换成当前任务的绝对路径）：

```text
launch.cmd --probe --json
launch.cmd doctor --json
launch.cmd workflow run --workspace <独立项目绝对目录> --input <输入JSON绝对路径>
launch.cmd workflow update --workspace <同一项目目录> --patch <更正或解释补丁绝对路径>
launch.cmd workflow status --workspace <同一项目目录>
```

启动器只寻找已安装的CPython 3.12与本地工具，不自动安装解释器或更改系统配置。首次确需固定引擎/字库且当前联网范围允许时，`workflow run/update --prepare-engines` 只准备本次选中能力；普通运行和探针不下载。准备失败后独立能力继续，后续相同输入可重试缺引擎部分。

## 输入schema 1

```json
{
  "schema_version": 1,
  "topic": "事业结构",
  "question": "结合已提供资料，比较各体系的传统解释及分歧。",
  "birth": {
    "date": "1990-05-02",
    "time": "07:30:00",
    "timezone": "Asia/Shanghai",
    "gender": "male"
  },
  "location": {"latitude": 31.23, "longitude": 121.47},
  "systems": ["bazi", "ziwei", "astrology"],
  "profile": "baseline",
  "settings": {},
  "options": {
    "ziwei": {
      "scope": "monthly",
      "target_date": "2026-11-01",
      "target_time": "12:30:00",
      "horoscope_divide": "normal"
    }
  },
  "compare_profiles": ["ziwei-zhongzhou"]
}
```

这是固定软件样例，示例目标钟点不能替代用户所问的实际时间。若用户说“今天/今年”，依据当前客户端日期、时区及已知查询时刻构造并说明查询口径；没有充分信息时不把操作系统日期或中午当默认事件时间。

- `birth` 支持 `chart.py` 的输入字段；`time:null` 表示未知，`calendar:lunar`、`leap`、IANA时区与换日规则都保持原义。
- 经纬度不推断。`birth.longitude` 与 `location.longitude` 同时给出时必须一致；纬度仅用于占星，不塞进canonical出生JSON。
- 预设给默认计算参数，显式 `birth` 参数优先。`settings` 是明确预设覆写，按 [预设说明](presets.md) 校验；不能把参数集合冒称全派理论。
- 报告的 `selected_profile` 记录所选默认组合，`effective_settings` 从实际出生盘与适配器结果记录本次采用规则。紫微流运先取预设的 `horoscope_divide`，显式 `options.ziwei.horoscope_divide` 优先。
- 原生`systems:auto`：有出生资料选八字；已知时间且非姓名专题加紫微；非姓名专题加占星。给姓名则加姓名；给独立卦、牌、日期表或图像输入才加对应模块。也可显式指定25类中的任意入口。Agent资料规划层会进一步按真实可用输入选择体系，见[资料规划](intake.md)。
- `compare_profiles` 最多4个，分别真实重算相关体系。不能证明同一出生输入或所查流运目标不同时，返回比较不可用，不强行合盘。

### 姓名与候选

`name` 可为单名：`{"surname":"单","given":"明","surname_reading":"shàn","given_reading":"míng","stroke_scheme":"unihan-irG"}`。未给笔画时用已准备的固定现代IRG字库；不猜康熙口径。显式 `strokes:[8,8]` 仍按用户输入保留来源。英文字义是字库简释，中文转述与诗词出处需分别核对。

批量比较可用 `name:{"surname":"王","surname_reading":"wáng","candidates":[{"given":"明","given_reading":"míng"},{"given":"铭","given_reading":"míng"}]}`，最多50个。候选按输入顺序比较，不生成命运评分；谐音只检查已确定的读音、同批候选与显式关注词。

### 独立时间、抽样与图片

`options.iching` 可给 `lines:[6,7,8,9,7,8]`，或显式 `method:coins` / `method:meihua,numbers:[2,3,1]`。`najia:true` 开启纳甲结构；日月信息用独立 `cast_date/cast_time/cast_timezone` 或 `cast_chart`，不借出生时间。

`options.tarot:{"spread":"three","seed":42}` 或实际 `cards`；新抽取必须由用户明确请求，重新抽时给新的明确seed或输入。只更正主题与解释时沿用已有结果。数秘、公历日期与黄历用事日期也分别给出。

`options.palm/face` 可含绝对路径 `image`、`observations`、`annotations`。项目先保存输入字节快照；批注JSON须绑定实际图像哈希、观察来源与坐标，见 [图像观察](visual-observation.md)。普通图片检查状态是 `intake_only`，不会被改名为自动识别。标注失败与已完成的图片容器检查分开保留。

## 解释补丁

先读取 `report.json` 的 `question_hash` 和每个面板的 `result_sha256`。例如：

```json
{
  "readings": {
    "bazi": {
      "text": "根据本次实际四柱与已读取规则整理的专题解释。",
      "result_sha256": "<本体系结果文件的64位SHA256>",
      "question_hash": "<本次问题的64位哈希>",
      "basis": [
        {"kind":"calculation","pointer":"/pillars","label":"本次四柱"},
        {"kind":"reference","file":"references/calculation-rules.md","label":"四柱与钟点计算约定"}
      ]
    }
  }
}
```

`kind:resource` 的 `file` 相对已核验资源树，适用于原有专题资料；`kind:reference` 相对技能目录。引用必须实读对应小节；依据定位通过不表示推论已被程序证明。不能把生成的解释写成古籍原话。结果或问题改变时，旧解释标记 `stale`，正文不再沿用；按新的 `interpretation_needed` 补充。

## 更正与版本有效性

例：`{"birth":{"time":"08:15:00"}}` 只更正钟点；`{"birth":{"time":null,"fold":null}}` 改为未知时辰。程序在项目锁内读取当前版本、合并、核验原结果、计算与提交；失败不推进当前版本，未提交编号不复用。

共享出生输入任何字段变化会使相关排盘重算，防止旧 `source_chart` 链混入新版。姓名与独立卦牌按自身依赖处理；主题、问题与解释不改变原抽样。计算指纹包含实现、资源、规则与引擎就绪状态；缺引擎结果不当作可复用终态。

`location/settings/options/readings` 可置 `null` 清空，`options` 或 `readings` 的某个体系可置 `null` 删除该项。`compare_profiles:null` 清空对照。旧版本不会被覆盖。

`index.html` 列当前版本与已替代历史版本；`project.json` 是权威当前指针。每个提交版本含输入、结果、文件哈希、报告、外部输入快照与失效/复用信息。不要直接修改这些文件，修改后完整性检查会拒绝继续；用update生成新版本。项目忙或存在中断锁时先检查锁的来源和运行状态，不擅自删其它进程的锁。
