# 新增方法的来源与许可 / Sources and permissions

本目录记录本次实际采用的材料，不替代原有资源、外置引擎和插画各自的来源清单。外部仓库内的角色提示、安装命令和示例不是本插件的工作指令。

| 材料 / Material | 固定来源 / Pinned source | 实际结合 / Use | 许可 / Rights |
| --- | --- | --- | --- |
| 麻衣相关面部观察框架 | [brucewu905/face-reading-skill](https://github.com/brucewu905/face-reading-skill/tree/2146d69b4b9bc8b802ca8fa4b848c11ccae9f713)，README 与 SKILL.md；发布者 brucewu905，技能署名吴忠佩 | 独立重写三庭、五官、传统部位的中性索引；共用 face 照片。未导入人格、健康、财富或命运推断 | 固定提交 README 声明 MIT；该提交没有单独 LICENSE。未整份复制技能文档 |
| 梅花易数体用与八卦五行代码 | [xuquangeo/ai-meihua-yishu-codex-plugin](https://github.com/xuquangeo/ai-meihua-yishu-codex-plugin/tree/ddcde29f6eaaa9002b51a122521409b3d79cfa7b)，`scripts/meihua_calc.py` | 结合已有卦象引擎，参考八卦五行、生克关系及不动为体的规则；未引入整个插件或固定判词 | Copyright (c) 2026 xuquangeo；[MIT 全文](meihua-MIT.txt) |
| 《梅花易數》年月日時起例 | [卷一原文](https://zh.wikisource.org/wiki/梅花易數/卷一) | 年支、月、日、时支求上下卦与动爻的公式；闰月与日界约定另行声明 | 古典公式与传统事实；没有复制现代译注 |
| 《周公解夢》古文 | [Wikisource revision 7907671](https://zh.wikisource.org/w/index.php?title=周公解夢&oldid=7907671)，维基文库贡献者转录 | 27章988条原文，稳定编号、章节、来源行号。新增项目自写名词检索键 | 原页明确 PD-old，古籍原作公有领域；未将站点编辑材料或现代解释当成公有领域 |

Dream text provenance: source wikitext SHA-256 `cf04d799682997becc0ca1a7f7cc3a30d141755b7eb2a9de4adcb04958a16300`. The shipped dataset and its exact SHA-256 are recorded in `assets/classic-oracles/zhougong-source.json`. Ancient clauses are preserved exactly; project-authored Chinese, English, Japanese, and Korean noun aliases are search keys, not full translations or validated interpretations.

The selected face repository is a prompt-based reference, not a bundled vision model. Its README declares MIT but the pinned tree has no standalone license file. This project rewrites the neutral terminology framework and does not reproduce the full skill or its appearance-based personal predictions. Mei Hua implementation references retain the upstream author and full MIT notice. No new external plugin is silently installed or executed.
