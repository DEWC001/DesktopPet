# Changelog

本项目所有重要变更都会记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0] - 2026-08-30

> 本次更新围绕「换肤」与「互动性」展开：新增多皮肤支持、全新的
> feidudu（肥嘟嘟）3D 卡通皮肤、皮肤专属台词、动作切换台词气泡，
> 并对素材生产链路（抠图）做了完整梳理。原企鹅皮肤保留为默认皮肤。

### 新增

#### 换肤系统
- **托盘「更换皮肤」菜单**：动态扫描 `assets/skins/` 下含全部 6 个动作帧的
  子目录，互斥单选；切换即时生效（保持窗口中心，托盘图标同步刷新）。
- 皮肤选择持久化到配置（`skin` 键），重启后保留。
- 当前可用皮肤：
  - `默认（企鹅）`：`assets/skins/` 根目录（原版）
  - `feidudu`（肥嘟嘟）：`assets/skins/feidudu/`

#### feidudu（肥嘟嘟）皮肤
- 共 **9 个动作帧**（260×260、透明背景、底部对齐、水平居中）：
  - 基础 6 帧：`idle`（叉腰回头）/ `blink`（单眼闭+捂嘴）/
    `walk_a`（伸手比 V）/ `walk_b`（镜像）/ `jump`（缩放上移）/ `sleep`（闭眼抱物）
  - 扩展 3 帧：`drink`（捧杯喝水）/ `think`（摸头思考）/ `laugh`（捂嘴笑）
- 扩展帧按需加载：皮肤目录里存在则启用对应动作，不存在时自动回退 `idle`，
  对其它皮肤零影响。
- 素材来源：用户提供的 12 张 3D 卡通形象（含报时拿怀表、坐姿鼓肚、捧杯、
  坐键盘、趴地托腮等），经透明化处理后选帧映射。
- 原图配文（如「肥嘟嘟的胆子，在此」）已从动作帧中裁除；右下角抠图水印
  已清除。

#### 台词系统（互动性增强）
- **feidudu 专属台词**：随机自语追加 7 条、点击回应追加 6 条，均带
  「肥嘟嘟」风格（如「你的胆子真是肥嘟嘟的～」「我的胆子，肥嘟嘟的！」）。
  仅在 feidudu 皮肤时混入，默认企鹅皮肤台词保持原样。
- **动作切换台词气泡**：状态机切换动作时随机弹出台词，增强互动：
  - `walk`：出去溜达一圈～ / 肥嘟嘟去巡逻了～
  - `jump`：飞起来啦！ / 胆子肥，跳得高！
  - `sleep`：困了，眯一会儿～ / 胆子鼓鼓，先睡为敬～
  - `wander`：去那边看看 / 肥嘟嘟巡逻时间到
  - `drink`：喝口水润润嗓 / 肚皮嘟嘟，喝水补补
  - `chat`：复用随机自语（feidudu 追加专属台词）
- **台词冷却机制**：同一状态 8 秒内不重复弹气泡，避免频繁切换刷屏。

#### 素材生产链路（开发）
- 新增 `assets/skins/feidudu/` 素材目录与处理脚本（开发产物，不打进 exe）：
  - `_process_v4.py`：cv2 GrabCut 抠图 + 缩放对齐（260×260）
  - `_process_v5_kotu.py`：基于高质量透明原图生成 6 基础帧
  - `_process_v6_extras.py`：生成 drink/think/laugh 扩展帧
  - `_rewalk.py` / `_clear_text.py`：配文裁除辅助脚本

### 变更

- `pet/config.py`：
  - 新增 `skin` 配置项、`DEFAULT_SKIN`、`list_skins()` / `current_skin()`；
  - 新增 `FEIDUDU_MESSAGES` / `FEIDUDU_CLICK_MESSAGES` 专属台词与皮肤感知的
    `get_random_messages()` / `get_click_messages()`；
  - 新增 `ACTION_QUOTES` 动作台词表、`get_action_quotes()`、
    `ACTION_QUOTE_COOLDOWN=8`。
- `pet/window.py`：
  - `_load()` 改为按当前皮肤路径加载 `skins/<皮肤>/<帧>.png`；
  - 新增 `set_skin()` 方法（保存配置、重载帧、重建缓存、居中保持、图标刷新）；
  - 新增 `EXTRA_FRAME_NAMES` 扩展帧加载与 `_override_frame` 临时帧机制
    （双击 1.5s `laugh`、喝水 10s `drink`）；
  - `_current_frame_name()`：CHAT 状态使用 `think` 帧；
  - `_on_state()` 末尾调用 `_emit_action_quote()` 弹动作台词（带冷却）。
- `pet/tray.py`：
  - 新增「更换皮肤」子菜单（动态扫描、互斥单选、`_sync_skin_checks`）；
  - 新增 `_build_idle_icon()` / `refresh_icon()`，皮肤切换后同步托盘图标。
- `assets/skins/`：新增 `feidudu/` 皮肤目录。
- `.gitignore`：新增排除皮肤开发产物（`**/_thumb/`、`**/yuantu/`、`**/kotu/`、
  `**/_process*.py` 等），避免素材中间产物进入仓库。

### 移除

- **删除 `yellow_pet` 皮肤**（2026-08-29 曾新增的 AI 生成测试皮肤）：
  其 6 帧为 AI 生成 RGB 不透明图、带白边羽化，显示效果不佳，已整体移除
  （含目录与 git 跟踪）。

### 修复

- **透明背景问题**：此前 AI 生图请求「透明背景」实际返回 RGB 不透明图，
  桌宠会显示白底方块。现统一改用 **cv2 GrabCut 抠图**（`opencv-python-headless`）
  获得干净的透明背景，角落 alpha=0、无白边。
- **抠图方案迭代**（开发链路）：
  - `rembg` 无法安装（HuggingFace 模型源不可达）→ 弃用；
  - flood fill（边缘采样背景色）在浅黄+浅灰背景上过度抠图 → 弃用；
  - 最终采用 GrabCut + 形态学清理，效果稳定。

### 打包与部署

- `dist/DesktopPet.exe`：onefile 单文件，含全部皮肤资源。
  - 1.1.0 之前（yellow_pet + kotu 素材入包）：约 117~118 MB；
  - 1.1.0（移除 yellow_pet，扩展帧入包）：约 112 MB。

### 已知事项

- 本机 git 推送依赖 PAT（GitHub MCP 连接器 App 为只读权限）。
- `build.bat` 硬编码了原作者的 Python 路径，本机重打包需手动执行
  `pyinstaller` 命令（详见 git 提交说明）。
