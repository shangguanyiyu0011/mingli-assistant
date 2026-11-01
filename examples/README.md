# 完全合成的演示报告 / Synthetic demo

这里的“演示人物 A（虚构）”是软件展示用的完全合成人物。称呼、出生资料、提问、牌序和土占四母均为明确设定，不对应真人，不使用任何以前个案、真人照片或标注。正文里的工作、关系与居住场景都是假设，不能当作真实经历或预测验证。

This example is entirely synthetic. No real person, prior case, photograph, or personal annotation was used. The report's life situations are hypothetical and its traditional symbolism does not establish predictive validity.

## 1.0.1 新增方法示例 / New oracle example

另设“虚构演示者 B”，没有生日、地点或照片。梅花采用明确数字 `[2,3,1]`，实际为泽火革初爻动、之卦泽山咸、互卦天风姤，体兑金、用离火。梦境中的旅伴、渡河、船与蛇全部新设，检索真实古文后分别阅读；梦境与词条不作为独立预测证据。

- [新示例请求](synthetic-oracles-request.json)、[完整离线 HTML](oracles-demo.html)、[5页 PDF](oracles-demo.pdf)。
- [预览与摘要记录](oracles-preview-provenance.json)：PDF第4页为[梅花](../docs/screenshots/meihua.png)，第5页为[解梦](../docs/screenshots/dream.png)，均为180 DPI实页。
- 实际流程完成两种方法的正文绑定及针对性总结；119个文字块、18段源正文无缺漏。原六方法示例保持独立，不以旧真人案例改名生成新示例。

This second example is also fully fictional. It uses no birthday, location, photos, or prior personal case. Mei Hua uses explicitly supplied numbers; the dream section remains textual reference material. Both HTML and PDF were produced through the actual report workflow. Screenshots are full PDF pages, not browser mockups.

- [示例请求](synthetic-request.json)：公开的固定演示资料。
- [完整报告 PDF](demo-report.pdf)：14 页，含六种方法、六个生活主题和三条行动建议；文字可选择、检索。
- [逐方法正文及绑定](synthetic-readings.json)、[六主题综合及绑定](synthetic-synthesis.json)：本次 Agent 根据实际结果新写的正文，供查看生成链条。
- [预览来源记录](preview-provenance.json)：PDF 与 PNG 的 SHA-256、页码和图片尺寸。

## 六方法示例 A 的资料

| 项目 | 固定设定 |
| --- | --- |
| 人物 | 演示人物 A（虚构） |
| 出生 | 公历 2000-02-14 09:30:00，female |
| 出生时区 | Asia/Shanghai；按当地钟表时间，不作真太阳时修正 |
| 出生示例地点 | 北京，纬度 39.9042、经度 116.4074 |
| 提问 | 2026-10-20 14:00:00，Asia/Shanghai |
| 提问示例地点 | 北京，纬度 39.9042、经度 116.4074；在请求中独立明确填写 |
| 所选方法 | 八字、紫微斗数、西方占星、塔罗、雷诺曼、西方土占 |
| 塔罗 | 三牌反思：太阳正位、星币二逆位、节制正位 |
| 塔罗合法 ID | `major-19:upright,pentacles-02:reversed,major-14:upright` |
| 雷诺曼 | `[1,9,24]`：骑士、花束、心；无逆位 |
| 土占四母 | `["1111","2222","1212","2121"]`；16 图盾盘、顺序宫位 |
| 随机抽样、引擎准备 | `virtual_draws=false`、`prepare_engines=false`；本次均未执行 |

六种方法均由原生流程实际计算或记录。实际四柱为庚辰、戊寅、壬寅、乙巳；紫微命宫在酉、身宫在夫妻；热带黄道太阳水瓶、月亮双子、上升白羊。牌序与四母是手工演示设定，报告没有假称进行了实体洗牌或随机抽取。

## 生成步骤

这是一项发行素材维护任务，使用已确定的合成资料；没有向任何个人收集新资料。

1. 以 `synthetic-request.json` 执行 `agent_report run`，建立独立工作目录；使用已有、已校验的本地引擎，不下载或准备新引擎。
2. 阅读本次六项实际结果及对应规则，新写每项正文；用实际 `result_sha256` 与 `question_hash` 绑定，通过 `workflow update` 保存。
3. 重新取得 `agent_report status` 的综合上下文，新写“个人特点、事业与发展、财务与财运、爱情与关系、家庭与居住、近期重点”六个主题；每个主题引用本次相关方法的真实结果。
4. 通过 `agent_report deliver` 的演示标识导出完整离线 HTML 和 PDF；本次使用允许的本地文字、矢量与插画排版，不启动浏览器。保留随包原创敦煌青金山水和牌面。
5. 用 Poppler 从 PDF 实页生成 PNG，不制作仿网页截图。导出后核对 340 个预期文字块和 56 段源正文，均无缺漏。

在 Windows 仓库目录可从以下命令开始（工作目录建立在仓库之外）：

```powershell
$repo = (Get-Location).Path
$demoWork = Join-Path (Split-Path $repo -Parent) 'synthetic-demo-work'
$request = Join-Path $repo 'examples/synthetic-request.json'
$handoff = .\launch.cmd agent_report run --request $request --reports-dir $demoWork | ConvertFrom-Json
$personWorkspace = $handoff.people[0].workspace
$job = $handoff.job_dir
$readings = Join-Path $repo 'examples/synthetic-readings.json'
.\launch.cmd workflow update --workspace $personWorkspace --patch $readings
.\launch.cmd agent_report status --job $job
```

正文与综合中的摘要只绑定这份示例的资料、结果和正文。若计算版本或参数变化，应读取新结果并更新绑定，再通过 `agent_report deliver --example` 交付；不要沿用失效摘要。PDF 导出能力随宿主环境而异，本文的预览页码专指随附的正式 PDF。约 21.5 MB 的离线 HTML 未放入 Git 版本库。

## 预览与 PDF 页码

下面六张示例 A 预览为 180 DPI、1489 × 2105 的完整页面；每页页眉均保留“演示人物 A（虚构）”。新增示例 B 的页码另见上节。

| PNG | PDF 页码 | 内容 |
| --- | ---: | --- |
| [overview.png](../docs/screenshots/overview.png) | 1 | 虚构标识、示例资料、敦煌山水与目录 |
| [bazi.png](../docs/screenshots/bazi.png) | 6 | 实际四柱与十神表 |
| [ziwei.png](../docs/screenshots/ziwei.png) | 8 | 本命十二宫与二〇二六年流年 |
| [astrology.png](../docs/screenshots/astrology.png) | 10 | 实际星位、宫位与相位图 |
| [cards.png](../docs/screenshots/cards.png) | 11 | 塔罗三牌、正逆位与原创插画 |
| [lenormand.png](../docs/screenshots/lenormand.png) | 12 | 雷诺曼骑士、花束、心 |

例如复核塔罗预览，可对随附 PDF 执行：

```text
pdftoppm -f 11 -l 11 -singlefile -r 180 -png demo-report.pdf cards
```

公开文件只保留合成资料与必要的生成来源信息，不包含本机绝对路径、引擎缓存位置、凭据或旧个案记录。
