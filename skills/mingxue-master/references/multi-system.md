# 体系能力与综合报告

综合分析与资料更正优先用 [一键流程](workflow.md)：批量运行、依赖复用、失效重算和解释绑定均由项目程序记录；以下单体系命令仍可独立使用。

## 当前能力

| 体系 | 实际支持 | 限制 |
|---|---|---|
| 八字 | 共用时间换算、基础结构、原有17组资料与命例 | 传统解释与现实预测效度分开 |
| 周易/六爻 | 64卦、动变互错综、虚拟三钱、纳甲世应六亲；旧数字梅花调用继续兼容 | 保留历法候选；未实现完整用神、伏神、应期与综合断卦 |
| 梅花易数 | 独立保存两数/三数或明确年月日时起卦、本互变及体用五行关系 | 不借生日、机器当前时间或新随机数；传统结构不转换成现实概率 |
| 周公解梦 | 每人独立梦境，检索27章988条有来源古文，再结合实际叙述解读 | 文字参考，不是心理诊断或现实事件预测；不命中时不编古文 |
| 紫微 | 十二宫、命身宫、五行局、星曜、生年四化；显式目标日期的年/月/日流运 | 首用外置引擎；未知时辰不假盘；性别依赖字段分开；节界遵从实际引擎口径 |
| 西方占星 | 实际行星黄经、星座、逆行、相位；明确坐标时宫位 | 外置引擎；不按日期段伪造星盘 |
| 吠陀基础 | 恒星黄道、明确岁差、月宿几何 | 不含完整吠陀分盘、大运和断法 |
| 姓名 | 固定外置字库的字形、现代IRG笔画、读音、英文简释与异体；五格三才、候选比较与有界谐音提醒 | 康熙/姓名学折算不自动猜；多音需选择；不作命运评分 |
| 数秘 | 生命路径、年度数、主数及拉丁字母数 | 归约约定明示，不猜汉字拼音 |
| 塔罗 | 完整78牌、正逆位、牌阵、虚拟抽样和手工输入 | 抽样是本次实际软件操作，不代表现实预测 |
| 黄历/择日 | 中国UTC+08日期表宜忌、值日、冲煞与可选时辰表 | 不是全派个性择日 |
| 手相/面相·麻衣相法 | 图片输入检查、实际可见形态、三庭五官传统名称与原照AI标注；麻衣共用face照片 | 输入检查和标注不等于视觉事实已核；不由照片断人或诊病 |
| 风水 | 给定平面、方向、用途的资料分析 | 不自动飞星排盘，不保证现实收益 |
| 奇门/六壬 | 已有盘面、规则口径与术语资料 | 无完整自动起局引擎，不补造盘面 |
| 人类图 | 用户已有图的传统术语与输入说明 | 无完整自动闸门、通道引擎 |

具体工具和前置条件在 `systems.json`，按其中 `reference` 只读相关文档。

当前共27类入口：20类计算、抽取或历表，2类照片观察，4类已有资料参考，1类古文梦境检索。麻衣是面相的传统框架，不额外计数。新增来源、采用范围与许可见 [第三方说明](third-party/README.md)。梅花易数和周公解梦分别读 [meihua.md](systems/meihua.md) 与 [dream.md](systems/dream.md)，麻衣读 [mayi.md](systems/mayi.md)。

## 输入与执行

- 八字、紫微、占星共享日期时优先先生成schema3。它保留物理UTC与已选钟点，但各体系的历法年界、月份和子时法仍各自声明，不能硬改成相同定义。
- 紫微/占星外置缓存与Python/Node要求见各模块。只有选中该能力时才准备固定依赖，离线要求下不擅自下载；其他已可用模式继续。
- 姓名保留用户明确的姓与名。可查固定外置字库的现代IRG笔画、读音候选与英文简释；用户指定康熙或其它折算时独立核对，不用现代数据替代。缺字、缺字段和多音未选均列待补。
- 卦、牌、用事时间和出生时间分别记录，不把一种输入偷换成另一种。用户已有卦或牌就直接处理，不额外重抽。
- 图像模块只在实际图像可用或用户提供观察时进行；左右手和清晰度不足就保留限制，不默认性别或惯用手。

## 统一命令

```text
python scripts/fortune.py --list
python scripts/fortune.py describe ziwei
python scripts/fortune.py bazi --date 1990-05-02 --time 07:30 --timezone Asia/Shanghai --save <绝对工作目录>/birth-v001.json
python scripts/fortune.py bazi --bazi 癸巳 甲子 丁酉 甲辰
python scripts/fortune.py iching --lines 6,7,8,9,7,8 --najia --save <绝对工作目录>/hexagram.json
python scripts/fortune.py names --surname 张 --given 三 --strokes 11,3
python scripts/fortune.py numerology --date 1990-05-02
python scripts/fortune.py tarot --spread three --seed 42
python scripts/fortune.py electional --date 2026-11-01 --days 7
python scripts/fortune.py palm --image <本地图像路径>
```

统一 `--save` 只接受技能、资源和外置缓存之外的新绝对路径。文件中保存原始系统JSON，stdout外层标明体系；原生 `--output` 仍按各工具规则使用，两者不同时给。周易目录导出使用其原生 `--catalog --output`。

```text
python scripts/fortune.py prepare ziwei --engine-dir <外部引擎目录>
python scripts/fortune.py prepare astrology --engine-dir <外部引擎目录>
python scripts/fortune.py ziwei --chart <绝对工作目录>/birth-v001.json --engine-dir <紫微目录> --save <绝对工作目录>/ziwei.json
python scripts/fortune.py astrology --chart <绝对工作目录>/birth-v001.json --latitude 31.23 --longitude 121.47 --engine-dir <占星目录> --save <绝对工作目录>/astrology.json
python scripts/fortune.py bundle --item bazi=<绝对工作目录>/birth-v001.json --item ziwei=<绝对工作目录>/ziwei.json --item astrology=<绝对工作目录>/astrology.json --topic 事业 --output <绝对工作目录>/bundle.json
```

`bundle` 仅汇集已有结果，并比较所声明的共享输入哈希，不重新验证计算或生成命运概率。输入链冲突时先重算受影响报告。只有用户有意比较不同对象或不同口径时使用 `--allow-different-inputs`；同一体系的不同面板用 `bazi@甲=路径`、`bazi@乙=路径` 明确区分。这也不会自动生成合盘结论。

## 综合报告

先概括用户所问，再按“体系—采用口径—实际依据—传统解释—待核实项”并列呈现。只写真实执行或阅读的内容；未准备引擎、资料型模式和看不清图像明确说明。

主题相似可以作为不同传统的叙事对照，不能称多体系共同证明。分歧先检查出生数据、钟点、年界与各派定义，仍无法统一就保留，不以多数意见裁决。没有共同输入链的结果不能默认属于同一个人的同一次排盘。

## 5.0 可视版新增方法

小六壬、六壬金口诀、七政四余、太乙神数、宿曜、焦氏易林、灵棋经、雷诺曼、西方土占与卜卦占星已加入。各自规则与输入见 systems/ 下同名说明，完整可视能力与启动见 [可视工作台](workbench.md)。原生JSON接口统一为 `extra_methods.py SYSTEM --params JSON`，Web表单会明确转换常用输入，不把提问时刻借用成出生时刻。
