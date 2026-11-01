# 紫微斗数

本模块可运行本命排盘，以及显式目标日期/时辰的真实流年、流月、流日排盘。本命含十二宫、命身宫、命主身主、五行局、主辅星/杂曜、亮度、生年四化及三方四正索引；流运另列当层十二宫映射、四化落宫和流曜。只有明确提供传统规则性别时，才输出完整性别相关星曜、长生/博士十二神、大限和小限字段。软件排盘正确不等于命理预测得到科学验证。

## 准备与运行

需要 Python 3.12+、Node.js 和 npm。引擎固定为 `iztro 2.6.3`，适配 ABI 为 `1`。引擎安装在 Skill 外部缓存，不放入 Skill，也不全局安装。以下是**首次显式准备命令**，会下载依赖，关闭安装脚本执行：

```powershell
python scripts/prepare_ziwei.py
python scripts/ziwei.py --probe
python scripts/ziwei.py --date 2000-08-16 --time 03:30 --gender female
python scripts/ziwei.py --date 2000-08-16 --time-index 2
python scripts/ziwei.py --chart birth-chart.json --gender female
python scripts/ziwei.py --chart birth-chart.json --scope yearly --target-date 2026-10-31 --target-time 12:00
python scripts/ziwei.py --date 2000-08-16 --time-index 2 --gender female --scope daily --target-date 2023-08-19 --target-time 03:12
```

默认缓存由 `runtime_paths.engine_directory('ziwei','2.6.3')` 定位到系统用户级持久缓存，Windows 默认位于 `%LOCALAPPDATA%/mingxue/engines/ziwei/2.6.3`。可用 `MINGXUE_ZIWEI_ENGINE` 或 `--engine-dir <外部目录>` 指定；准备脚本和排盘必须采用同一目录。自定义缓存不得位于 Skill 内。准备脚本固定引擎及其运行依赖，验证下载包的固定完整性摘要，保留外部完整性清单，不执行安装脚本。排盘和 `--probe` 完全离线，不会自动下载。缺少引擎时，JSON 返回 `needs_setup` 和可执行的准备参数。旧版本独立准备的缓存仍可通过显式路径复用，标记 `engine.integrity=legacy_version_only`；带新完整性清单的缓存须通过验证，标记 `verified`。这两个标记描述缓存验收方式，不代表预测置信度。

输出写到标准输出，含 `status`、引擎版本/ABI、输入、历法口径、`chart.palaces`、`soul_palace`、`body_palace`、`natal_mutagens`。未提供性别时计算两种真实规则，输出共有部分，状态为 `partial`；`gender_dependent_omitted` 列明未确定字段。不会假设男命或女命。

共享 schema3 输入时，`source_chart` 含该盘 `input` 的规范 JSON SHA256，供跨体系核对实际出生输入链；直接日期/时辰输入时为 `null`。哈希不等于命理结论一致或预测置信度。

## 时间与历法口径

- `--date` 是**已采用钟点的公历生日**。`--time` 是对应钟点，支持 `HH:MM`、`HH:MM:SS`。直接输入不推断城市/时区，不默认减夏令时，也不自动加真太阳时修正。需要历史时区或真太阳时，先用共享 `chart.py` 得到已采用的时间，再传 `--chart`。
- `--time-index` 是明确时辰：0=早子（00:00..00:59），1=丑（01:00..02:59），2=寅（03:00..04:59），依此至11=亥（21:00..22:59），12=晚子（23:00..23:59）。不能同时传 `--time` 和 `--time-index`。只知道“子时”而不知早晚时，请保留两种候选，不随意选0或12。
- `--chart` 只接受共享 `chart.py` 的 schema 3，采用唯一候选的 `time.chart_clock`，不二次校正。共享盘仍未知时辰、有多个候选、夏令时重复钟点未解决，或真太阳时处于边界附近时，返回 `needs_input` / `ambiguous_input`，不生成完整紫微盘。
- 紫微历法基准是**采用钟点的公历日期交给紫微引擎换算农历**。海外采用钟点的公历日期可能不同于同一真实瞬间的中国 UTC+08 日期。本模块不把共享八字盘的中国农历标签硬套到紫微生日。输出 `convention.calendar_basis` 及共享盘输入说明保留这一差异。
- 默认 `--year-divide normal` 按农历正月初一换生年；可显式改为 `exact` 采用引擎立春规则。八字年柱默认按真实瞬间的立春、月柱按节令，和本模块年界、月份框架可能不同。紫微输出 `chineseDate` 仅为引擎内部历法字段，不覆盖共享八字四柱。
- 默认 `--day-divide forward` 为晚子按次日安星；`current` 为晚子按当日早子安星。它是紫微安星选项，不能用八字 `sect` 直接替代。23点仅表示采用明确的规则，不说明其他规则错误。
- 默认 `--fix-leap` 把闰月前15日按本月、16日起按次月处理；晚子 `forward` 的月份索引遵循固定引擎特例，不再手工移月。`--no-fix-leap` 关闭半月调整。公历输入时引擎自行识别实际闰月，不另传一个臆测的闰月标志。
- 适配器验收范围为公历1900..2100年。超出范围返回 `unsupported_range`，不外推。

## 流派与解读

`--algorithm default` 使用引擎通用规则；`--algorithm zhongzhou` 使用引擎中州算法。后者是有限安星算法选项，不代表包含该派所有口传实践。四化、亮度按固定引擎与所选算法的默认表输出，不混入其他派别的四化表。若要比较其他规则，应分别排盘并列差异，不在同一盘暗改星曜。

解读先确认本宫主辅星、三方四正、空宫对宫、四化落宫和亮度，再把判断写成有条件的传统解释。`surroundedPalaces` 的 target/opposite/wealth/career 是引擎给出的本宫、对宫、财帛位、官禄位索引。名称是相对于目标宫的关系，不能误认为总是本命财帛宫和官禄宫。只引用实际返回星曜；空宫没有主星是有效结果，不增补虚构星曜。

## 显式目标流运

`--scope` 可选 `origin`（默认本命）、`yearly`（流年）、`monthly`（流年+流月）、`daily`（流年+流月+流日）。非本命时必须给出 `--target-date YYYY-MM-DD`，以及 `--target-time HH:MM[:SS]` 或 `--target-time-index 0..12` 中的一个。不会把系统今天、当地当前钟点、出生时辰或默认午时当成目标时辰。目标日期必须在公历1900..2100年范围，且不能早于采用的出生日期。

目标钟点是用户明确采用的钟点；该模块不自动沿用出生地时区、推断目标所在地、修正夏令时或重复修正真太阳时。目标生日历法和目标时辰单列在顶层 `target`，流运结果位于 `horoscope`；本命宫位和 `natal_mutagens` 继续独立保留。流运通过实际本命对象的 `horoscope(target_date,target_time_index)` 生成，不重排一张目标生日的本命盘冒充流运。

`horoscope.layers` 含实际查询层及其上层。每层保留引擎的 `index`、`palaceNames`、`heavenlyStem/earthlyBranch`、按禄权科忌顺序的 `mutagen` 星名及分十二宫的 `stars`；`flow_mutagens` 把该层四化映射到真实本命星所在物理宫位，`palaces` 给出本命宫名、当层宫名和当层流曜。流曜的 `scope` 必须等于所在层，不能把本命主星改标签当作流曜。无性别输入时分别计算两种真实规则，只有相同的流运层可输出，大限/小限上下文抑制；若所求层确实依赖性别，返回 `needs_input`。明确性别时，大限/小限超出引擎覆盖范围的负索引会抑制为 `unavailable`。

流运口径单列于 `horoscope.convention`，不能从本命口径自动推定：

- `--horoscope-divide normal` 为默认，流年在农历正月初一切换，月干支按农历月；闰月前15日/16日起分段。`exact` 为固定引擎的立春日期/节月干支规则：**年界不是精确交节瞬间**，月干支用时辰代表点判断；流月宫位仍按农历月份和闰月半月定位。它独立于本命 `--year-divide`。
- 引擎干支计算会把时辰置于代表点：早子为00:30，其他时辰取该时辰起始小时的30分，包括晚子23:30。输入分秒用于记录用户选择，不用于引擎的精确交节判断。不能用此接口覆盖共享八字排盘的真实瞬间节令计算。
- 引擎流运总是按实际闰月的1..15日和16日起分段，流月定位也考虑出生闰月后半月；本命 `--no-fix-leap` 不会关闭流运这一实现。分别记录两类设置，不能声称同一个开关控制所有层。
- `--day-divide current` 的目标晚子干支按当日早子；`forward` 的晚子目标日干支按次日，但**流日宫序仍用目标原农历日**。这是固定引擎的实际实现，输出保留这一差异，未手工改成统一切日。要求统一23点换流日宫序或交节秒级精度时，该引擎不满足，不能隐瞒限制给出完整精确断语。
- 大限/小限上下文按农历年虚岁规则（`ageDivide=normal`）。流年/流月/流日的四化与本命生年四化分别保留，不代表已实现飞宫、全套自化、合盘评分或格局自动断语。不计算未经依据的量化匹配率。

综合命理时，先把每个体系实际排盘、历法口径和传统解释分开记录，再比较一致点与差异。不能因结论不同就改动任一体系排盘，也不能称多体系一致即证实事实或预测效力。
