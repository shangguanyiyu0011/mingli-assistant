# 七政四余：可视天文底盘与明确约定

入口为 `scripts/astral_methods.py`，使用 `calculate("qizheng", params)`。必须明确提供事件公历日期、时间、IANA 时区及经纬度；不默认中午或根据城市猜位置。时间复用共享 schema 3，再调用已准备的固定隔离星历引擎，普通计算与探针均不联网安装。

```powershell
python -X utf8 -B scripts/astral_methods.py qizheng --params '{"date":"2024-04-08","time":"18:00:00","timezone":"UTC","longitude":0,"latitude":51.48,"house_system":"W"}'
python -X utf8 -B scripts/astral_methods.py qizheng --probe
```

七政为太阳、月亮、水星、金星、火星、木星、土星的真实视地心日期黄经与速度。输出 `candidates[].bodies`，点型 `physical_body`。负黄经速度标记逆行。默认热带黄道；恒星模式必须明确 `zodiac="sidereal"` 和受支持的 `ayanamsa`，二者不会混用。

四余单列为 `four_remainders`，不能作为四颗可观测行星：

- 罗睺、计都：月球交点轴。`node_model=mean|true` 选择平交点或真交点；`node_orientation=ascending|descending` 明确罗睺取升交点还是降交点，计都恒取相反 180°。方向与名称映射是所选约定，不宣称各时代、流派完全一致。解析真交点精度有别于实体行星，不承诺角秒以下精度。
- 月孛：本模块采用平均月球远地点作为现代几何参考，标明 `MEAN_APOG` 与映射约定；不是声称已复刻所有古历均速表。
- 紫气：默认 `ziqi={"model":"not_calculated"}`，没有已确认历元就不造数。可明确给出 `mean_cycle`、`epoch_utc`、`epoch_longitude`、`period_days`、`reference_label`，按 TT 经过日数作均速参考计算。公式及选定黄道记录在点的 `algorithm` 中，历史流派相位未独立校准。示例周期 10227 日仅代表 28 个儒略年，不把任意参考零点宣传成古法标准。

输出 `wheel` 包含十一点记录，但未计算的紫气经度为 `null`，仅列状态，不绘制。实体用实点，交点/远地点用空心，均速紫气用虚线。默认 `W` 为明确的西方整宫黄经显示参考，可选既有宫制；不冒充已重建中国地支十二宫规则。没有经过历元、距星与坐标框架核验的二十八宿界表时，`lunar_mansions.status=not_calculated`，不使用随意等分或固定偏移臆补宿度。

分钟输入保留整分钟起点与独占终点轮盘；回拨重复钟点保留两个 UTC 候选，此时顶层 `wheel=null`，须选择 fold。极地所选宫制不可用时保留七政及计算点，宫位单独报不可用，不暗中换宫制。默认紫气缺历元、分钟精度或多候选等情况返回 `partial`，与计算失败分开。

该模块提供天文底盘与传统计算点结构，不生成命运确定论。宿度、古代宫制及未经校准的历史四余行表仍需具备可核验口径后再扩展。
