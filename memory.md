# 2026-05-26 运行记录

- 当前执行方式：不再使用 `.codex/worktrees` 永久 worktree，后续统一直接在当前仓库工作区推进代码修改。
- 自动化约定：后续运行先读取本文件，再继续识别下一个未完成模块。
- 本次已恢复的环境能力：
  - `powershell` 可用
  - git 可用
  - `& "E:\ForANACONDA\python.exe" --version` 成功，返回 `Python 3.12.7`
- 本次已完成模块进度：
  - 已完成 P0b 第 1 项核心落地：新增 `functions/strategy_registry.py`
  - 已将策略元数据统一到注册表：策略名、分数字段、排序方向、来源、说明文本
  - 已将 `main.py` 的策略枚举与说明读取切换到注册表驱动
  - 已将 `functions/feature_engineering.py` 的多策略生成切换为遍历注册表，不再手写逐条策略分支
- 本次继续推进：
  - 为主题倾斜增加显式配置开关：`ENABLE_HOT_THEME_BIAS`
  - 为 learning 策略增加总开关：`ENABLE_LEARNING_STRATEGIES`
  - 为 learning 策略增加白名单：`LEARNING_STRATEGY_WHITELIST`
  - 让注册表按配置输出启用中的策略集
- 本次校验：
  - `& "E:\ForANACONDA\python.exe" -m compileall ...` 通过
  - 默认注册表策略数为 24
  - 关闭 learning 策略后注册表策略数为 12
  - 指定单条 learning 白名单时注册表策略数为 13
- 当前工作区改动文件：
  - `config.py`
  - `main.py`
  - `functions/feature_engineering.py`
  - `functions/strategy_registry.py`
- 下次运行优先事项：
  1. 先读取本文件
  2. 继续 P0b：补主干核验脚本，检查关键产物与字段完整性
  3. 修改后继续使用 Anaconda 解释器做最小导入/编译/聚焦校验
