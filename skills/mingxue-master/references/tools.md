# 工具用法

以下路径以技能目录为当前目录示意；工作目录和输出目录应替换成当前任务的绝对路径。使用 Python 3.10 或以上版本，Windows 可加 `-X utf8` 避免终端中文编码问题。历法库已随资源提供，无需联网安装。

## 环境和资源

```text
python scripts/doctor.py --json
python scripts/resources.py
```

doctor 检查 Python、资源清单、工具导入和数据计数，不联网、不安装软件。资源使用完整SHA和逐文件校验；缓存缺失、内容损坏或混入多余文件时重建。默认缓存在系统临时目录，可用 `MINGXUE_CACHE_DIR` 指向技能目录外的独立目录。`MINGXUE_RESOURCE_DIR` 仅供开发时指定已解包且与清单完全匹配的资源，不允许跳过校验。

## 统一排盘与真实时间换算

```text
python scripts/chart.py --date 1990-05-02 --time 07:30 --timezone Asia/Shanghai --sect 2 --output <工作目录>/chart.json
python scripts/chart.py --date 2023-02-01 --calendar lunar --leap --output <工作目录>/chart.json
python scripts/chart.py --date 1990-05-02 --time 07:30 --timezone Asia/Shanghai --gender male --yun-sect 2 --output <工作目录>/chart.json
python scripts/chart.py --date 2024-11-03 --time 01:30 --timezone America/New_York --fold 1 --output <工作目录>/chart.json
python scripts/chart.py --date 1990-05-02 --time 07:30 --timezone Asia/Shanghai --longitude 121.47 --true-solar --output <工作目录>/chart.json
```

- `--sect 1` 表示23点换日，`--sect 2` 表示零点换日；默认2并在JSON中记录。23时可能另列其他口径候选，不能混作同一确定结果。
- 未提供 `--time` 时输出未知时辰及边界候选，不补入确定时柱。节气日的年/月柱可能同样未确定。
- `--timezone` 使用随包离线IANA数据做实际时区和历史DST换算，不需要全局安装时区包。默认Asia/Shanghai会标记为默认；输入其他地区应选择实际使用的IANA时区，不根据语言推断。
- `--time-basis local-clock|standard-time|true-solar-time` 表示原始输入性质：当地民用钟、已去DST的标准钟、已校正的真太阳钟。前两种可通过 `--true-solar --longitude` 计算太阳命盘钟点；已是真太阳钟时需经度反解实际瞬间，不能再重复太阳校正。
- DST跳时造成的不存在钟点会拒绝；重复钟点未给 `--fold` 时保留两个实际瞬间，明确选择早/晚一次后可用0/1指定。即使候选四柱相同也不合并成已确定出生瞬间。
- 年/月柱与起运用实际UTC瞬间转成库的UTC+08节气钟点；日/时柱用选择的当地或太阳钟点。输出保留原钟点、UTC、库钟点与命盘钟点，不能混用。
- 真太阳时采用已记录公式的近似均时差算法，需要经度东正西负。保留方法和临界限制，不宣称秒级天文精度。
- 农历输入按中国UTC+08历日解释；海外输入的实际民用日期可能前后跨日，输出明确列出。若原始农历来自其他记日口径，先核实或换成公历与IANA时区输入。
- 仅已知出生时间、真实瞬间已确定且明确给出 `--gender male|female` 时计算起运。`--yun-sect` 记录所选节气换算方法，输出完整年/月/日/时及起运日期，不套平均起运数；DST候选未定时分别保留其影响。
- JSON使用 `schema_version=3`，包含 `input`、`time_context`、`pillars`、`details`、`candidates`、`uncertainty`、`yun` 等字段。基础结构的逐柱表与关系位置见 `details` 及 [计算约定](calculation-rules.md)。候选分别带基础结构，未知日干的十神/长生保持null。
- 后续工具复用完整JSON，不手改字段。旧schema 2文件须按原资料核实时区和钟点后重新生成，工具不会静默改变旧盘；2.0版文件保留作历史记录。
- 真实日期与时间换算限定输入年份1583及以后，并受历法库上界约束；更早记录仍可直接按三/四柱查询和计算基础结构。IANA历史钟点按所给口径和数据重建，不等于历史出生记录已经核实。

## 本地命例查询

```text
python scripts/case_lookup.py --chart <工作目录>/chart.json --json
python scripts/case_lookup.py --bazi "癸巳 甲子 丁酉 甲辰" --limit 8 --json
python scripts/case_lookup.py --birth 1990-05-02 --time 07:30 --timezone Asia/Shanghai --json
```

三种输入互斥。三柱或四柱按六十甲子严格校验；`--birth` 与 `--chart` 共用同一排盘API。未知时辰不按四柱完全一致匹配。结果分为 `four_pillars`、`three_pillars`、`similar`、`same_day`，`--limit` 是每层最多条数。候选未定时分别查询并标出，不能拼成已确定结论。

显示 `sources`、`confidence`、`caution` 和 `variants`；其中原材料质量标签不代表本次核验或个人概率。质量审计另列完整性、内容重复、旧指纹碰撞和异说标记，不改写原记录。历史记录本身有异说时必须保留。

需要重新审计内置库时使用 `scripts/case_audit.py`，命令行参数见其 `--help`。当前质量索引为 `<resource_root>/references/case-quality.json`，必须与实际JSONL的SHA匹配。没有可核对的生辰原始材料时不把程序分组标为已验证人物身份。

## 铁板入口

```text
python scripts/tieban_run.py --chart <工作目录>/chart.json --gender 男 --json
python scripts/tieban_run.py --year 癸巳 --month 甲子 --day 丁酉 --hour 甲辰 --gender 男 --birth-year 1953 --json
python scripts/tieban_run.py --chart <工作目录>/chart.json --gender 男 --qiyun 6 --json
```

无 `--qiyun` 时，依赖起运的值运和书传流年返回 `not_calculated`，基础起数、原文查询仍可进行。`--qiyun` 只接受经核实的整数岁数；不能把统一排盘的精细起运结果自动截成年数填入。时辰缺失、多候选未定或输入冲突时拒绝起数。

23时存在换日口径差异时，确认实际采用的口径后可加 `--confirm-sect 1|2`，数值须与共用排盘一致；此参数不改盘，也不要求用户重复确认已有明确选择。

考刻参数如 `--kaoke --kaoke-facts '{"brothers_n":1}'` 透传给引擎，默认JSON输出会区分反馈前和反馈后状态。只有用户明确要求逐岁条文时才启用 `--liunian14` 并补齐该功能所需农历信息。原文含过时说法时作为传统文本展示并解释，不贴给用户作为事实标签。

考刻状态区分“未考刻、进行中、已收敛并应用”。空反馈或全为未知不算已校准；部分有效事实也不自动代表考刻完成。未知/不确定与明确的否、0分别处理；负数、小数计数等非法输入明确报错。

## 保留反馈前后版本

仅在需要保存当前交互档案时使用，目录必须在技能源码之外。

```text
python scripts/feedback.py init --workspace <绝对工作目录> --case case01 --input <工作目录>/chart.json --report <工作目录>/before.json
python scripts/feedback.py revise --workspace <绝对工作目录> --case case01 --facts <工作目录>/facts.json --report <工作目录>/after.json --note "根据本次自述调整解释"
python scripts/feedback.py show --workspace <绝对工作目录> --case case01
```

报告文件应是JSON，可包含自由文本解释。facts文件格式：

```json
[{"kind":"user_fact","statement":"用户本次提供的事实原话","source":"user"}]
```

初始报告保留，修订追加记录。每条含时间与hash链，可检测局部篡改；完整替换档案需用另存的回执hash通过 `--expected-head` 进一步比对，不能称为绝对防篡改。用户事实与模型推断分栏保存，反馈后的吻合不算反馈前命中。

## 搜书

```text
python scripts/book_search.py search "The Art of War" --sources archive --archive-collection gutenberg --limit 3 --agent-model <实际执行模型> --work-dir <绝对工作目录>
python scripts/book_search.py download 1 --session <本次session_id> --format txt --agent-model <实际执行模型> --output <下载目录> --work-dir <同一工作目录>
```

默认来源是Internet Archive公开馆藏API；支持按馆藏集合筛选、列出实际文件与格式，下载前复核公开状态和来源文件信息，下载后核对内容、大小与来源校验和。来源声明单列，不把公开收录当作已经独立核对全球授权。

兼容书源保留显式选择，实际可达性受网络和来源服务影响。`annas` 当前仅返回人工跳转说明，不宣称已完成检索；可选 `zlib` 必须显式选择且所需环境凭据已配置，不自动启用，不读取浏览器cookie。请求模型标识应填写实际执行模型或环境中已核实的值，不能沿用测试模型名冒充当前执行者。

搜索与下载是独立动作；下载必须有本次会话ID，使用多源合并后的统一序号。空搜索产生新空会话，不复用旧结果。搜索会报告每个来源的状态，输出是单个JSON。只有用户请求联网或下载时执行。

`--timeout` 为每次网络操作超时（默认30秒），`--retries` 为额外重试次数（默认1，最多3）。TLS校验保持开启。有效文件才原子发布到下载目录，HTML/错误页、格式不匹配和断流均报告失败；不覆盖同名文件。

默认缓存位于系统临时目录；可用 `--work-dir` 或 `BOOK_SEARCH_WORK_DIR` 指定本次工作区，不可放在技能源码目录内。

真实联网观测、来源能力和版本字段解释见 [搜书来源与实测](book-sources.md)。这是一轮指定样书的验收，不保证来源日后始终可用。

## 离线验收

在技能根目录运行：

```text
python -B -X utf8 -m unittest discover -s tests -v
```

测试验证边界排盘、输入复用、命例层级、缓存修复、无起运时的降级、条文原文、反馈版本保留及搜书的模拟网络行为；不验证命理预测有效性，也不访问真实书源。某些系统不允许创建符号链接时，该专用测试会明确跳过，仍执行目录逃逸模拟检查。
