# 表情帧

三张眨眼帧只替换 `pet.png` 的双眼区域；头发、脸、服装、姿势、透明边缘均继续来自母版：

- `pet_blink_open_v1.png`：睁眼基准帧，独立眉毛位移 0px。
- `pet_blink_half_v1.png`：半闭眼。
- `pet_blink_almost_v1.png`：接近闭合。
- `pet_blink_closed_v1.png`：完全闭合。

运行时按实际帧顺序开合，不再使用睁眼/闭眼交叉淡化。两侧眉毛同步使用 0px、3px、6px、8px 的纵向位移，并按相同幅度返回。

## AI 表情资产

以下三张运行时图片只从 AI 结果提取脸内表情；头发、脸部轮廓、身体、服装和透明边缘仍来自 `pet.png`：

- `pet_expression_curious_v1.png`：好奇，双眼睁大、小圆嘴。
- `pet_expression_annoyed_v1.png`：轻微不满，眉毛内压、抿嘴。
- `pet_expression_sleepy_v1.png`：困倦，双眼半闭、轻微哈欠。

AI 原图和对齐中间图保存在 `ai_sources/`，不直接用于运行。右键菜单的“预览表情”可检查三种状态。
