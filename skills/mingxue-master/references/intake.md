# 基础表与独立个人／双人报告入口


## 零基础填写的地点与时间

普通用户不填写经纬度和时区。每人可用`birthplace`保存城市／区县及国家／省份，`birth.timezone`可省略；提问用独立`preferences.cast_place`与`cast.datetime_utc`（实际UTC瞬间），或明确历史`date/time`。收集阶段校验并保留未解析地点，不把未知时区换成任意默认。`agent_report run`先自动查实地点，再进入下面的完整原生协议；失败／歧义会给可读补问并停止计算。既有完整输入仍兼容。

只保留一版填写，补充资料按需展开，直接支持照片；出生时间可选准确钟点、时辰或不知道。时辰以time=null和shichen保存，子时保留早晚两段。真实姓名明确选择分析后使用姓／名；不需要提供`strokes`，后续姓名工具查询字库。默认字库不是康熙折算表，不混淆来源。


`scripts/intake_flow.py` 提供资料规范化与独立个人/双人报告接口。由Agent调用时，使用[一次性资料表](agent-intake.md)只收集资料，再按[Agent工作流](agent-workflow.md)计算、解读和导出05敦煌青金HTML；填写表不进入最终报告。下面保留原生接口协议。

```python
from intake_flow import normalize_request, plan_request, submit
validated = normalize_request(request)  # 纯校验，不建任务目录、不准备引擎
plan = plan_request(request)            # 补全路由，保留缺条件，不抽样
result = submit(server_reports_root, request)
```

`server_reports_root` 必须为服务端配置的绝对目录。用户提交不能指定路径、图片文件、字典、引擎、工作区或保存位置。任务目录与插件、运行时、引擎缓存及 Python 目录双向隔离。

## 请求协议

```json
{
  "mode": "single",
  "people": [{
    "person": {"name": "甲方称呼", "notes": "本人提供的可选说明"},
    "birth": {"date": "2000-08-16", "time": null, "calendar": "solar", "timezone": "Asia/Shanghai"},
    "location": {"latitude": 31.23, "longitude": 121.47},
    "name": {"surname": "王", "given": "明", "strokes": [4, 8]}
  }],
  "preferences": {
    "systems": "all",
    "topic": "综合分析",
    "question": "本次独立问题",
    "depth": "detailed",
    "relationship": "伴侣",
    "answers": {"当前关注": ["学习", "时间安排"]},
    "virtual_draws": false,
    "prepare_engines": false
  },
  "method_options": {}
}
```

- `single` 严格一人，`pair` 严格两人。每人必填称呼、出生日期、历法与 IANA 时区。称呼不是身份证明，不从称呼拆猜姓名，也不从履历或问答补造出生事实。
- 出生钟点支持 `HH:MM`、`HH:MM:SS`；省略、空字符串和 `null` 都表示未知。出生历法支持 `solar/lunar`，农历闰月须显式 `leap:true` 且实际存在；基础历法范围为 1583—9998 年。
- `gender` 可省略，若采用当前传统紫微规则则明确 `male/female`；未提供会保留待补条件。不能从姓名、照片或称呼推断。
- 坐标须成对、有限且在经度 ±180、纬度 ±90 内。未知坐标可省略整个 `location`。姓名学必须明确 `surname/given`；显式笔画按姓后名顺序，每字 1—64，同字同口径不可矛盾。
- `answers` 只接受最多 50 个可读文字键及文字／文字数组；独立存入 `questionnaire`，不会修改出生资料。问答用于了解关注点，不是预测有效性的验证。
- `systems` 为 `all`、`auto` 或 1—25 个无重复的准确体系 ID；综合默认选 `all`，会规范化为全部25个ID。所有对象拒绝未知参数、非有限数、布尔冒充整数、循环及超大 JSON；完整请求上限 256 KB。双人关系背景由系统保留字段加入工作流上下文，用户问答仍最多50项，不能自填 `_relationship_context`。
- `method_options` 使用各体系原生参数，不接受文件或安装目录。它对双方共用规则选项；本人事实由每人的基础表生成，出现两处冲突明确拒绝。需要不同人物选项时分别提交个人任务。
- `prepare_engines` 默认 `false`；只有明确 `true` 才传递引擎准备授权。未准备的真实引擎会保留引擎不可用状态，不伪造结果。

## 自动路由与待补条件

自动选择八字、数秘、宿曜；已知钟点及传统性别时加紫微；已知钟点及出生坐标时加占星；明确姓与名时加姓名学。非空的显式 `method_options` 也表达了选用该体系的意图，会加入自动选择。

明确选择 25 个入口不等于 25 个体系均已完整实现。资料不够或本工具仅提供资料阅读时，工作流收到 `deferred`，该方法返回 `needs_input`，其余可算方法继续。个人报告会显示需补内容，`submit` 同时返回可跳过的 `questions`。缺经度而选择真太阳时，会将依赖该共享出生钟口径的方法一并待补，保留用户原设置；独立数秘与宿曜可继续。

| 方法 | 本入口所需事实／授权 |
| --- | --- |
| 八字 | 未知时辰保留实际候选；真太阳时必须有经度 |
| 紫微 | 明确出生钟点与当前所用传统性别规则；流运另有 `scope/target_date` 及 `target_time` 或 `target_time_index`，钟点与序号互斥 |
| 西占／吠陀基础 | 明确出生钟点与坐标；吠陀仅为已实现的恒星盘基础 |
| 七政四余 | 本人的出生日期、钟点、时区与出生坐标；当前真实天文范围 1583—2999 年 |
| 卜卦占星 | `preferences.cast` 的独立提问日期、钟点、时区，加本次明确 `question` 及提问地点；绝不借用出生地点 |
| 太乙 | 显式中国日期、分钟钟点、`Asia/Shanghai`，另明确原生 `mode/method`；当前历法校验范围 1900—2100 年 |
| 小六壬 | 明确三个正整数，或显式独立 `cast`；后者统一转真实 UTC+08 中国农历月日及 UTC+08 时支，闰月按同编号；多个不一致候选则待补 |
| 金口诀 | 显式 `cast` 及 `earth_branch`；手工另给日柱、时支、月将，时间法选所用换将规则；不从问题猜地分 |
| 择日 | 显式 `cast.date` 与 `Asia/Shanghai`；仅已实现的黄历表检索，不是全派个性择日 |
| 周易 | 明确实际六爻、梅花起数；软件三钱需 `virtual_draws:true`；起卦历法必须独立显式，不借生日 |
| 易林 | 明确 `base/changed` 卦对、实际六爻或已核验周易结果；虚拟三钱需明确授权 |
| 灵棋经 | 明确上中下各 0—4 的实际棋数或十二枚面值；虚拟投十二棋需明确授权 |
| 塔罗／雷诺曼／土占 | 明确实际牌、四母或点数；没有实物输入时必须明确授权虚拟抽样，seed 本身不等于授权 |
| 手相／面相 | 仅接收结构化本人可见观察，标为 `not_observed`；不接受客户端本地图片路径，不自动识别，不推断人格、健康或命运 |
| 风水／奇门／六壬／人类图 | 当前基础表入口保留资料阅读及待补项，不由生日生成未实现盘面 |

提问地点可写入 `preferences.cast.latitude/longitude`，或卜卦原生参数成对提供；两处均明确而矛盾时拒绝。提问时区不会默认中国时区。太乙、黄历要求的中国时区也不会偷偷替换其他时区。

虚拟抽样在最终结果保留实际 seed、算法及抽样记录。没有 seed 时由相应方法生成后记录。灵棋投十二枚正反再累计，上中下 125 种棋数并非等概率。起式概率不是事件预测概率。

## 返回与公开文件

```json
{
  "status": "partial",
  "job_id": "32位小写随机十六进制",
  "files": [{"role":"personal_a","title":"甲方的个人报告（含待补条件）","filename":"personal-a.html","url":"/files/任务标识/personal-a.html"}],
  "warnings": ["明确的实际限制"],
  "questions": [{"person_index":0,"person_name":"甲方","system":"ziwei","question":"待补说明","required_inputs":["出生钟点"],"optional":true,"choices":["补充资料后重新生成","暂跳过此方法"]}]
}
```

`ready` 表示选中项目已生成可交付文件；`partial` 表示文件真实生成且仍有缺条件或计算限制；必填基础缺失为 `needs_input`，非法数据为 `invalid_input`，生成过程失败为 `error`。后三种不会返回假成品文件。`ready` 也不代表预测有效或完整流派已实现。

每次提交使用 `secrets.token_hex(16)` 新任务目录，双方分别为 `project-a` 与 `project-b`。个人页面只从已提交、摘要校验有效的工作流版本复制。双人合参只读双方已提交的真实 `report.json` 与各结果 JSON，不重排盘或重抽牌。

服务端文件路由只能公开任务顶层这三个准确文件名：`personal-a.html`、`personal-b.html`、`pair.html`。不要把整个任务目录设为静态目录；提交数据、项目历史、原始结果、观察及错误记录为私有文件。返回值不含服务端绝对路径。页面经过外部／相对依赖检查，内联脚本、样式、数据和盘面支持独立离线阅读。

该接口为一次新提交，不复用旧任务 ID。补充资料后重新提交会得到新报告。当前不含用户登录、远程分享、任意图片上传、批量候选姓名输入或视觉风格选择实现；这些应由后续界面与服务明确接入。
