# 🐱 桌面宠物（Desktop Pet）

一个会眨眼、会呼吸、会说话、还会赖在屏幕边缘的桌面宠物。基于 **Python + PySide6（Qt 6）** 开发，无边框置顶透明窗口，不会占用任务栏。

> 素材由 AI（GPT 5.6）生成，见文末[素材版权声明](#素材版权声明)。

## ✨ 功能特性

- **待机动画**：呼吸起伏 + 轻微摆动 + 脚下阴影，随时保持"活着"
- **自动眨眼**：随机间隔自然眨眼，边缘贴边时还有专门的贴边眨眼状态
- **屏幕边缘吸附**：拖到屏幕左右边缘会自动"贴上去"，像趴在屏幕边上
- **开心动画**：单击桌宠播放 20 帧开心动作（带帧间平滑过渡）+ 随机说句话
- **行走动画**：右键菜单开启，原地循环播放
- **拖拽交互**：可以抓着拖走，拖拽中有姿态过渡、松手有落地缓冲
- **表情切换**：右键切换不同表情（开闭眼等）
- **说话气泡**：圆角带箭头的气泡，会跟随宠物移动，3 秒自动消失
- **始终置顶**：不会挡住你干活，也不占任务栏

## 🚀 快速开始

### 环境要求

- Windows 10 / 11
- Python 3.9+（建议 3.10+）

### 安装运行

```bash
# 1. 安装依赖（只需要 PySide6）
pip install -r requirements.txt

# 2. 启动
python main.py
```

### 使用方法

| 操作 | 效果 |
|------|------|
| 单击桌宠 | 播放开心动画 + 随机台词 |
| 左键拖拽 | 移动桌宠，可拖到屏幕边缘吸附 |
| 右键菜单 | 行走动画 / 表情 / 说句话 / 退出 |

## 📦 打包为独立 exe

用 PyInstaller 把桌宠打包成单文件 exe，非技术用户**双击即可运行**，无需装 Python：

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name DesktopPet \
    --add-data "happy_*.png;." \
    --add-data "walk*.png;." \
    --add-data "pet.png;." \
    --add-data "assets;assets" \
    main.py
```

产物在 `dist/DesktopPet.exe`（约 170MB，已含全部素材）。注意 `--name` 用英文名，中文名会被 PyInstaller 处理成 `default.exe`。

## 🎨 自定义素材

素材文件直接放在项目根目录或 `assets/` 下，桌宠启动时**自动扫描**，无需改代码：

- **动画帧**：命名 `happy_01.png`、`happy_02.png`… 自动按序号播放；
  帧间中间帧命名为 `happy_01_1.png`、`happy_01_2.png`（源帧名后加 `_序号`），放入即自动插帧。
- **待机图**：修改 `main.py` 顶部 `MASTER_CHARACTER_IMAGE`。
- **角色图层/表情**：`assets/character/` 下有分层素材与说明文档。

详细说明见 [assets/character/character_spec.md](assets/character/character_spec.md)。

## 📁 目录结构

```
桌宠/
├── main.py                    # 主程序（约 1100 行）
├── assets/
│   └── character/             # 角色分层素材、表情、动画帧
│       ├── character_spec.md  # 角色素材规格说明
│       └── ...
├── tools/                     # 素材准备/生成脚本（含 AI 生图后处理）
├── requirements.txt           # 依赖清单
└── 启动桌宠.bat               # Windows 双击启动脚本
```

## ⚠️ 素材版权声明

- **角色美术素材**由 AI 模型 **GPT 5.6** 生成，遵循其服务条款。
- 代码部分采用 MIT 许可证。
- 若你要**商用**本项目素材或二次分发素材，请自行确认生成工具的最新服务条款。

## 📄 许可证

本项目代码基于 [MIT License](LICENSE) 开源。

## 🙏 说明

- 本机若遇到 `DLL load failed`（Anaconda 环境下 Qt 加载失败），属于本机 Python 环境的 VC++ 运行时版本问题，与项目代码无关；换用干净的 Python 3.10+ 环境即可正常启动。
