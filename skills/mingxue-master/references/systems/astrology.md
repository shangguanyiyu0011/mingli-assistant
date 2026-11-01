# 西方本命占星：真实黄经与不确定性

使用 `scripts/astrology.py`。输入先经过共用 `chart.py` 的 schema 3 历法与时区转换，再以 `time_context.valid_utc_ranges` 中的物理 UTC 计算。不能把八字采用的真太阳时墙钟直接当 UTC，也不能按月份日期段代替星盘。

## 能力与范围

- 热带黄道：太阳、月亮、水星至冥王星的视地心黄经、黄纬、距离和黄经速度；速度为负才标记逆行。默认采用日期黄道与春分点。
- 主要相位：合相、六合、刑、拱、冲；采用黄经最短角距。容许度为六合 5°，其余 6°，是可见的解释规则，不是自然常数。
- 已知时间且明确提供经纬度：上升、天顶与十二宫宫头；默认 Placidus `P`，可显式选择 `K/O/R/C/E/W`。行星 `house_longitude_only` 仅按黄经落入宫头区段，忽略黄纬。宫制有流派差异。
- 恒星黄道：必须同时给出 `--zodiac sidereal --ayanamsa lahiri`（或 `fagan-bradley`、`raman`）。输出 `zodiac.ayanamsa`、每个候选的 `ayanamsa_degrees` 和天体 `nakshatra` 的 27 月宿等分序号、名称及 pada。这里只提供几何基础，不等于完整吠陀分盘、大运或断命。
- 本准备版本明确选用内置解析星历模式，支持物理 UTC 公历 1583—2999 年。不会自行下载星历文件或暗中换后端。星历、历史时区、Delta-T 与未来闰秒都有精度范围；输出小数位不代表出生记录同样精确。

## 外置引擎

固定依赖 `pysweph==2.10.3.6`，本地准备轮子适用于 CPython 3.12 / Windows x86-64。技能包不含第三方运行库，不向全局 Python 安装依赖。

```powershell
python -X utf8 -B scripts/prepare_astrology.py --json
python -X utf8 -B scripts/astrology.py --probe --json
```

准备命令会显式下载固定 SHA-256 的轮子、校验后解包到持久外置目录（Windows默认 `%LOCALAPPDATA%/mingxue/engines/astrology/2.10.3.6`）。也可指定 `<work>/engine-cache/astrology`，通过 `--engine-dir` 或 `MINGXUE_ASTRO_ENGINE` 选择。缓存中保存完整依赖文件与逐文件校验。损坏时拒绝加载，显式 `--repair` 才替换并保留旧缓存备份。

`--probe` 与普通排盘只检查、使用本地缓存，绝不自动联网或安装。缺失或不兼容时返回 JSON `engine_unavailable` 和准备路径，星盘字段保持空值；不得用太阳日期表冒充计算结果。若当前 Python 不是指定运行环境，应先说明该限制。

## 命令

```powershell
python -X utf8 -B scripts/astrology.py --date 1990-05-02 --time 12:30:00 --timezone Asia/Shanghai --longitude 121.47 --latitude 31.23 --json
python -X utf8 -B scripts/astrology.py --chart C:/work/birth-chart.json --latitude 31.23 --json
python -X utf8 -B scripts/astrology.py --chart C:/work/birth-chart.json --latitude 31.23 --zodiac sidereal --ayanamsa lahiri --json
```

出生参数复用 `chart.py`：`--calendar solar|lunar`、`--leap`、`--time-basis local-clock|standard-time|true-solar-time`、`--true-solar`、`--fold 0|1`。太阳时选项只参与共享时间解析；行星仍使用解析后的物理 UTC。经度东正西负、纬度北正南负；时区不从城市或坐标自动推断。默认时区沿用共享转换器的明确软件默认值并在结果保留来源。

`--chart` 不接受新的出生日期、时间或历法覆盖。经度覆盖不能与共享输入矛盾；需要更正时先重建共用时间记录。`--output` 必须明确提供，且只能写到技能、资源和引擎缓存以外；默认仅 stdout，绝不把私人生辰留在技能中。

## 不确定性及解释规则

1. 时辰未知：保留完整 UTC 日内区间，只计算连续太阳黄经与可能太阳星座；跨星座边界保留两个候选及边界搜索区间。`candidates=[]`，没有默认中午，没有月亮、上升、宫位或精确相位结论。
2. 分钟精度：保留整分钟的半开 UTC 区间。候选起点 `representative_only=true`，同时给出 `end_limit`；两端是边界采样，不等于确定出生时刻。跨星座时顶层 `sun_sign=null`。
3. 重复民用钟：未指定 fold 时保留两个真实 UTC 候选，分别计算行星和上升；不得因八字相同而合并物理时刻。不存在的 DST 时间先由共享转换器拒绝。
4. 缺经度或纬度：行星仍可计算，宫位状态 `not_calculated`；不编造上升。极地导致所选宫制失败时状态 `unavailable`，保留行星，禁止自动改成另一宫制。
5. 解读先区分计算事实、约定和象征解释。不能把天文计算准确性说成人格、关系或未来预测已经得到验证；相同太阳星座不等于完整星盘相同。

关键输出为 `status`、`engine`、`time_context`、`zodiac`、`candidates`、`sun_ranges`。每个已知时间候选包含 `utc`、TT/UT1 儒略日、`planets`、`aspects`、`houses`；宫位、引擎及时间不确定性必须一并阅读。`source_chart` 记录共享 schema 3 输入的规范化 SHA-256，用于核验多体系是否沿用相同输入；该哈希不表示预测可信度。
