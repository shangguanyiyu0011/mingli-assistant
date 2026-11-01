# 上传照片后的Agent交接

本页给调用技能的Agent使用，不放入读者报告。首次资料表接收PNG/JPEG引用；提交后，可信CLI交接带有`photo_manifest`，`agent_report status`按A/B分别返回`photos`和`pending_photo_review`。只有实际打开本人对应文件、确认可见范围后，才能声明已经观察。

用`agent_report update --job <job> --person A --patch <新的JSON>`，更新本人的`observations`。例如以下是形状示意，ID及摘要必须从该人的真实交接记录取得，特征须来自实际查看：

```json
{
  "observations": {
    "palm": {
      "schema_version": 2,
      "source": "agent_viewed",
      "photo_refs": [{"id": "本人的实际32位照片ID", "sha256": "该文件实际64位摘要"}],
      "observations": {
        "hand": "unknown",
        "dominant_hand": "unknown",
        "quality": {"clarity": "clear", "mirrored": "unknown"},
        "features": [{"region": "thumb_arc", "shape": "curved", "visibility": "clear"}]
      },
      "note": "仅写这张照片中实际能看清的内容。"
    }
  }
}
```

人像使用`face`；质量、部位、形状枚举以`scripts/visual_intake.py`中的`QUALITY_VALUES`、`REGIONS`、`SHAPES`为准。左右手、惯用手和镜像不确定时保留unknown。用户自己的描述用`source:"user_reported"`，不能冒称Agent已看图；初始HTTP提交不接受agent_viewed声明。

看不清时也先实际查看，再记录真实质量和空的`features`，可在note说明模糊/遮挡。该照片已看过，但不会生成相应分析页；不能编造清晰纹路、补画看不见的线或用通用长文填充。清晰照片的实际观察仍是`intake_only`，不伪装成自动视觉计算；有绑定本人照片的可见特征和完整正文后才能单独显示。

脚本核对照片归属、引用、原文件摘要、观察记录和当前结果；直接更换他人文件、只改说明文件或混入旧结果都会拒绝。每人观察独立，不放到双人的全局method_options复用。上传并不自动进行识别；Agent必须实际使用宿主提供的图片查看能力。

照片按实际部位写具体形态、走向、明显程度和相邻关系，不由外貌推断人格、智力、道德、健康、寿命、身份或命运，不作为综合人格判断的证据。默认不嵌入报告，原图图库只采用逐张`include_in_report:true`的照片。用户明确要求原图划线时，可按[原图标注合同](illustrations.md)显式指定`use_original_photo:true`，仅展示带线条、编号和观察说明的标注图，不重复附一份原图。没有照片或没有足够可见内容时，目录、正文和覆盖行全部略去；私有工作记录保留真实原因。
