# 图像观察和覆盖标注

`visual_intake.py` 只读取 PNG/JPEG 容器、EXIF 方向及显式用户录入；不解码像素，不识别主体、手掌、脸或掌纹。清晰度、光照、阴影、透视、裁切、遮挡、左右手与镜像均由用户显式提供或保留 unknown；未提供不能推断。实际看图由观察者完成，无法辨认不等于不存在。不要从图像推断人格、智力、健康、寿命、身份或现实命运。

`visual_annotations.py` 只将实际看图后由用户或助理明确输入的坐标画到本地自包含 HTML，不识别、不验证标注正确性，也不上传。坐标基于原图左上角 (0,0)，x 向右、y 向下，单位是像素，边界为 0..宽与 0..高。标注区域使用对应手相或面相词表，几何为 polyline 或 polygon。只画实际可见的区域，不画推测的线。空数组可记录没有可标注的区域。HTML 包含图像和人工标注，以及绝对源路径、原图 SHA-256、坐标和观察来源；分享 HTML 即分享这些内容和原图。标注信息会被嵌入输出，原图不修改。

非默认 EXIF 方向 (2–8) 会被拒绝，需先制作方向归一化的独立副本、实际核查后在副本上重新取点；原图无方向或方向 1 时仍应确认查看器未对原图额外镜像/翻转。对手机自拍是否镜像与左右手由用户提供，不能根据拇指推断。已保存的 HTML 是快照，不能自动跟踪源文件的后续变化。仅支持 PNG/JPEG 容器且不保证数据可被浏览器成功解码，打开本地 HTML 检查原图和覆盖是否对齐。

示例（哈希替换成实际图片字节 SHA-256，所有路径均为本机绝对路径，输出必须是技能、资源和缓存之外的新 .html 文件）：

```json
{"system":"palm","image_sha256":"<64位小写SHA-256>","observation_source":"assistant_visual_observation","annotations":[{"region":"thumb_arc","geometry":"polyline","points":[[10,20],[30,40],[50,55]]}]}
```

```text
python <skill_root>/scripts/visual_annotations.py --image <absolute-image-path> --annotations <absolute-json-path> --output <new-absolute-html-path>
```

`observation_source` 为 `user_visual_observation` 或 `assistant_visual_observation`，仅记录谁声称实际观察，不是系统自动校验。手相和面相可用区域见对应模块。条目不会生成个人判断，原图路径及标注 JSON 路径会如实显示并做 HTML 转义。文件输出采用独占创建，避免覆盖已有文件。HTML 使用限制性 CSP 和本地 data 图像，不加载网络资源；不接受任意 HTML、自由标签或 SVG 指令。
