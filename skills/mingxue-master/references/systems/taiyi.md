# 太乙神数

本模块可实际计算年计、月计、日计、时计，支持统宗、金镜、淘金歌、太乙局四种积数算法。结果包含局式、积数、主客定算、太乙及主客将位置、八门、十六方位神将与九宫可视数据。分计、命法和其他扩展尚未验收，不开放。

## 准备与运行

主程序由既有 Python 3.12 编排。固定历法依赖当前没有对应的Windows Python3.12官方轮子，因此太乙使用**外部缓存内的私有Python3.11.9运行时**，不改变主Python、PATH或全局软件。初版固定依赖组合仅验收Windows x86-64。

```powershell
python scripts/prepare_taiyi.py --json
python scripts/taiyi.py --probe
python scripts/taiyi.py --params '{"date":"2026-03-24","time":"12:30","mode":"hour","method":1}'
```

准备命令是唯一联网步骤，显式下载固定引擎、官方私有运行时及固定轮子，逐个验证归档摘要，安全解包并在外部保存完整性清单。不会执行pip/npm安装脚本，不全局安装。以后运行和探针均离线，归档与实际文件内容都要通过验证；缺失返回 `needs_setup`，不在后台下载。

默认由共享持久缓存路径 `runtime_paths.engine_directory('taiyi',固定版本)` 定位。可用 `MINGXUE_TAIYI_ENGINE`、`--engine-dir <外部绝对目录>` 或API参数 `engine_dir` 指定。目录不能位于Skill、插件、资源包或Python安装内。已有缓存不合格时，准备器要求显式 `--repair`，保留旧缓存备份后修复。

## 输入与API

公开接口为 `calculate(params: dict) -> dict`，CLI的 `--params` 传同一JSON对象。

|参数|说明|
|---|---|
|date|必填公历 `YYYY-MM-DD`，初版1900..2100年|
|time|必填中国UTC+08采用钟点 `HH:MM`，不补时辰|
|mode|`year`年计、`month`月计、`day`日计、`hour`时计；默认year|
|method|整数0统宗、1金镜、2淘金歌、3太乙局；默认1|
|timezone|当前只接受 `Asia/Shanghai`，表示明确采用的中国UTC+08口径|
|engine_dir|可选外部绝对目录，通常省略|

境外时区、夏令时或真太阳时输入需要先明确换算成该引擎采用的钟点；本模块不根据城市猜时区，不将既有太阳时再修正一次。积年/积月取引擎农历年/月，干支年/月与积数体系并不必然使用同一边界。23点干支按次日，农历及积日/积时依固定实现另列，不把它们声称为共享八字盘的统一四柱。

## 结果与可视版

结果总含 `system=taiyi`、`status`、`input`、`rules`、`limitations`。成功时另含 `engine`、`chart`、顶层 `nine_palaces`。九宫数据与 `chart.nine_palaces` 相同，便于界面直接读取。

- `chart.bureau` 是真实引擎局式；`accumulated_number`、`host_count`、`guest_count`、`fixed_count` 分别为积数和主客定算。
- `chart.positions` 保存太乙、天乙、地乙、四神、直符、主将/主参、客将/客参等实际位置；`wenchang` 是文昌原方位。
- `chart.sixteen_palaces` 保留16个实际方位及神将；`central_palace` 单列中宫，不能把17个位置误称只有16个。
- `nine_palaces` 每格有 `number/name/direction/row/col`、实际八门 `door`（中宫可为null）、神将 `stars[{name,position}]`，以及保留原方位的 `sub_palaces`。布局北上南下，四角各包含三个细方位。它是可视容器，不把子方位的星将伪称为同一个精确宫位。

**太乙宫数与常见洛书编号不同**：1乾、2午、3艮、4卯、5中、6酉、7坤、8子、9巽。界面应采用后端row/col；不要把1自动放坎、6自动放乾。原方位标签及十六方位环必须保留，不能为了好看任意移宫。

## 已知边界

固定实现的日计method3把已取整积数返回为float，随后用于列表索引。适配层只在数值是可精确表示的整数时转为int，修复类型问题，不改公式和数值。

金镜时计在部分时刻产生零局，原实现不能给出有效神将盘。遇到该边界返回 `unsupported_boundary`，不会擅自改为六十局、补造星将或自动切换其他算法。用户可明确选择另一种算法后重新计算，结果应注明不同方法。

本模块只输出排盘的必要技术数据，不加载在线AI解读、博弈评分、营销、社交内容或确定灾害/战争预言。传统主客算和星将排布不证明预测有效性，也不输出未经校准的匹配率。
