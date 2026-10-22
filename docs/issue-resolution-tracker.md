# 开放 Issue 修复与验证台账

更新时间：2026-10-22。初始核对 main：`69ab991`；GitHub 实际开放 issue 初始95项。当前已合并 `48e03f7`（#140），该精确提交的 CI 与 CodeQL 已全部通过；逐项验证后已关闭6项，当前剩余89项开放。此表记录进展，不把计划、代码匹配或未完成的 PR 当成完成证据。

## 执行约定

- 按根因分批，隔离工作区并行；先复现与回归测试，再实现。
- 接管已有 PR #140、#141；新 PR 全部先 draft，不重复已有修复。
- 必要测试、CI、独立规格/质量审查通过后转 ready 并合并，不绕过检查、不强推。
- 合并后核对远端 main 实际 SHA 与该 SHA 的 CI；逐项证实后才关闭 issue。
- 不部署生产，不改用户正式配置、数据或安全设置。跳过项和平台验证边界如实记录。
- #114 用户决定：goal.md 一保存即用于后续实际执行，不需要单独发布；当前已开始的一轮不因自动保存而强杀。

## 逐项对应

| Issue | 问题 | 当前状态 | PR | 修复提交 / 验证证据 |
|---|---|---|---|---|
| [#43](https://github.com/isWANGBIAO/Vantage/issues/43) | [Bug][P2] 切换主题触发表单重载，保存时写回旧主题并丢弃未保存修改 | draft 已提交，正式 CI 中 | #142 | 11877f6 / 07e3cbb / e2bb9f8 / 3413f5e；配置97、严格合同124、600前端及真实UI主题回归 |
| [#44](https://github.com/isWANGBIAO/Vantage/issues/44) | [Bug] [P1] 空聊天消息误入行动计划生成并覆盖现有聊天上下文 | draft 已提交，CI lint 反馈已追加修正 | #143 | cba7d18 / 98bea3e / f007f37 / 510e35e；1863 Python、真实 HTTP→子进程→job→发布10项 |
| [#45](https://github.com/isWANGBIAO/Vantage/issues/45) | [Bug] [P2] 聊天内容为 --help 等单个连字符开头文本时被误当作子进程参数 | draft 已提交，CI lint 反馈已追加修正 | #143 | cba7d18 / 98bea3e / f007f37 / 510e35e；1863 Python、真实 HTTP→子进程→job→发布10项 |
| [#46](https://github.com/isWANGBIAO/Vantage/issues/46) | [Bug] [P2] CLI/MCP 将报错或缺少完成事件的聊天流标记为成功 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#47](https://github.com/isWANGBIAO/Vantage/issues/47) | [Bug] [P2] 设置 HTTP 写入未执行公开 schema，错误类型会启用自动生成或返回 500 | draft 已提交，正式 CI 中 | #142 | 11877f6 / 07e3cbb / e2bb9f8 / 3413f5e；配置97、严格合同124、600前端及真实UI主题回归 |
| [#48](https://github.com/isWANGBIAO/Vantage/issues/48) | [Bug][P1] 行动计划流截断后即使重试成功，仍被先前的错误事件永久判为失败 | draft 已提交，CI lint 反馈已追加修正 | #143 | cba7d18 / 98bea3e / f007f37 / 510e35e；1863 Python、真实 HTTP→子进程→job→发布10项 |
| [#49](https://github.com/isWANGBIAO/Vantage/issues/49) | [Bug][P1] 12000 字符中文提示词分块超过子进程行缓冲上限，导致行动计划失败 | draft 已提交，CI lint 反馈已追加修正 | #143 | cba7d18 / 98bea3e / f007f37 / 510e35e；1863 Python、真实 HTTP→子进程→job→发布10项 |
| [#50](https://github.com/isWANGBIAO/Vantage/issues/50) | [Bug][P2] 非空聊天请求遇到模型空回复时仍返回 done=true，用户消息未保存 | draft 已提交，CI lint 反馈已追加修正 | #143 | cba7d18 / 98bea3e / f007f37 / 510e35e；1863 Python、真实 HTTP→子进程→job→发布10项 |
| [#51](https://github.com/isWANGBIAO/Vantage/issues/51) | [Bug][P2] [首次引导] 跳过聊天后返回上一步，Provider 表单无法再次编辑 | 待按根因批次修复 | — | 待记录 |
| [#52](https://github.com/isWANGBIAO/Vantage/issues/52) | [Bug][P2] [导航] 返回首次打开的无 hash 地址时仍停留在后一个页面 | 待按根因批次修复 | — | 待记录 |
| [#53](https://github.com/isWANGBIAO/Vantage/issues/53) | [Bug][P2] [数据导入] Mi Fitness 与 Zepp 只识别写死的历史导出文件名，正常新导出被静默忽略 | 待按根因批次修复 | — | 待记录 |
| [#54](https://github.com/isWANGBIAO/Vantage/issues/54) | [Bug][P2] [财务] 摘要按工作表末行取值，倒序记录会把旧余额标为最新日期 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#55](https://github.com/isWANGBIAO/Vantage/issues/55) | [Bug][P2] [财务] 无实际记录时预测数据仍进入实际资产摘要和现金覆盖建议 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#56](https://github.com/isWANGBIAO/Vantage/issues/56) | [Bug][P2] [人脸历史] 单个零字节 JPG 使整批分析中断且后续照片无法处理 | 待按根因批次修复 | — | 待记录 |
| [#57](https://github.com/isWANGBIAO/Vantage/issues/57) | [Bug][P2] 行动计划来源指纹遗漏实际读取的 Prompt_System.md，修改后调度器不重新生成 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#58](https://github.com/isWANGBIAO/Vantage/issues/58) | [Bug][P2] 跨午夜生成的昨日输入被按完成日期标为今日计划，绕过日期校验并推进调度基线 | 待按根因批次修复 | — | 待记录 |
| [#59](https://github.com/isWANGBIAO/Vantage/issues/59) | [Bug][P2] [设置] 模型发现请求的迟到响应会重新创建已删除的 Provider | 设置交互与模型能力合同批次开发中 | — | 已分配；未完成验收，不关单 |
| [#60](https://github.com/isWANGBIAO/Vantage/issues/60) | [Bug][P2] [无障碍] AI Provider 的五个关键输入控件没有可访问名称 | 设置交互与模型能力合同批次开发中 | — | 已分配；未完成验收，不关单 |
| [#61](https://github.com/isWANGBIAO/Vantage/issues/61) | [Bug][P2] [设置] 语音“跟随 AI Provider”显示上次浏览的 Provider，与实际使用的默认 Provider 不一致 | 设置交互与模型能力合同批次开发中 | — | 已分配；未完成验收，不关单 |
| [#62](https://github.com/isWANGBIAO/Vantage/issues/62) | [Bug][P1] [设置] 重命名 Provider 路由会无提示删除已保存密钥，并可能切换到另一家服务 | 设置交互与模型能力合同批次开发中 | — | 已分配；未完成验收，不关单 |
| [#63](https://github.com/isWANGBIAO/Vantage/issues/63) | [Bug][P2] 语音转录成功响应只保留第一行，静默丢弃后续文本 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#64](https://github.com/isWANGBIAO/Vantage/issues/64) | [Bug][P2] 转录上传读取失败或被取消时，临时音频文件未清理 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#65](https://github.com/isWANGBIAO/Vantage/issues/65) | [Bug][P3] 大写扩展名 MP3/FLAC/M4A 被错误标记为 audio/wav 上传 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#66](https://github.com/isWANGBIAO/Vantage/issues/66) | [Bug][P2] [财务预测] 未补零的文本日期按字典序滚动余额，10 月资金被提前计入 2 月 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#67](https://github.com/isWANGBIAO/Vantage/issues/67) | [Bug][P2] [跑步导入] 一行合法 JSON 非对象值可终止整个 Mi Fitness 导入 | 待按根因批次修复 | — | 待记录 |
| [#68](https://github.com/isWANGBIAO/Vantage/issues/68) | [Bug][P2] [人脸趋势] 日聚合把本地日期当 UTC，负时区周/月图坐标轴提前一天 | 待按根因批次修复 | — | 待记录 |
| [#69](https://github.com/isWANGBIAO/Vantage/issues/69) | [Bug][P2] [财务接口] Excel 中的 inf/-inf 泄漏到 prompt_payload，整个资产负债表返回 500 | 待按根因批次修复 | — | 待记录 |
| [#70](https://github.com/isWANGBIAO/Vantage/issues/70) | [Bug][P2] [时间统计] 时长正则拒绝 30分，却把负数和小数截成正常小时数 | 待按根因批次修复 | — | 待记录 |
| [#71](https://github.com/isWANGBIAO/Vantage/issues/71) | [Bug][P2] [财务] 字符清洗篡改科学计数法与负号，1e3 被算成 13、负资产变正资产 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#72](https://github.com/isWANGBIAO/Vantage/issues/72) | [Bug][P2] AI_Prediction独立脚本的次日食物关联依赖同日行序 | 待按根因批次修复 | — | 待记录 |
| [#73](https://github.com/isWANGBIAO/Vantage/issues/73) | [Bug][P2] Never Stop新增/删除项目持久化失败后仍改变内存，后续操作会静默提交失败修改 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#74](https://github.com/isWANGBIAO/Vantage/issues/74) | [Bug] [P2] 用量统计把未上报 usage 的正常回复当成 0 token，导致总量和吞吐误导 | 待按根因批次修复 | — | 待记录 |
| [#75](https://github.com/isWANGBIAO/Vantage/issues/75) | [Bug] [P2] 夏令时/时区偏移变化会让启动修复误删仍在进行的模型调用 | 待按根因批次修复 | — | 待记录 |
| [#76](https://github.com/isWANGBIAO/Vantage/issues/76) | [Bug][P2] --skip-build 会删除已有后端打包产物，随后因缺失文件失败 | draft 已提交，依赖 #141 | #145 | 6b549f1 / 1bfb8e5；1841 Python +81子用例、611前端；真实spawn/截断HTTP/缓存回归 |
| [#77](https://github.com/isWANGBIAO/Vantage/issues/77) | [Bug][P2] skip-build 将新源码指纹写入未重建的旧产物，后续错误命中缓存 | draft 已提交，依赖 #141 | #145 | 6b549f1 / 1bfb8e5；1841 Python +81子用例、611前端；真实spawn/截断HTTP/缓存回归 |
| [#78](https://github.com/isWANGBIAO/Vantage/issues/78) | [Bug][P2] 后端尚未 ready 时退出桌面应用，已启动的后台进程不会被终止 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#79](https://github.com/isWANGBIAO/Vantage/issues/79) | [Bug][P2] 后端 spawn 异步失败未拒绝启动 Promise，错误只进入全局日志并继续等待 | draft 已提交，依赖 #141 | #145 | 6b549f1 / 1bfb8e5；1841 Python +81子用例、611前端；真实spawn/截断HTTP/缓存回归 |
| [#80](https://github.com/isWANGBIAO/Vantage/issues/80) | [Bug][P2] 状态探测遇到截断 HTTP 响应会永久 pending，启动超时失效 | draft 已提交，依赖 #141 | #145 | 6b549f1 / 1bfb8e5；1841 Python +81子用例、611前端；真实spawn/截断HTTP/缓存回归 |
| [#81](https://github.com/isWANGBIAO/Vantage/issues/81) | [Bug][P2] 打包缓存指纹写入中断后，下次 reuse 构建直接崩溃而不重建 | draft 已提交，依赖 #141 | #145 | 6b549f1 / 1bfb8e5；1841 Python +81子用例、611前端；真实spawn/截断HTTP/缓存回归 |
| [#82](https://github.com/isWANGBIAO/Vantage/issues/82) | [Bug][P2] 相机停止产出新帧后，实时人脸接口仍把旧图重新标为当前测量 | 待按根因批次修复 | — | 待记录 |
| [#83](https://github.com/isWANGBIAO/Vantage/issues/83) | [Bug][P2] Presence 推理只在开始校验帧，过期或已被替换的结果仍保存并覆盖实时检测框 | 待按根因批次修复 | — | 待记录 |
| [#84](https://github.com/isWANGBIAO/Vantage/issues/84) | [Bug][P2] [采购建议] 单条恢复排除项后没有放回推荐列表，页面刷新按钮也无法恢复显示 | 待按根因批次修复 | — | 待记录 |
| [#85](https://github.com/isWANGBIAO/Vantage/issues/85) | [Bug][P2] [仪表盘] AQI读取失败后仍把上次空气质量显示为当前值，没有过期或不可用提示 | 待按根因批次修复 | — | 待记录 |
| [#86](https://github.com/isWANGBIAO/Vantage/issues/86) | [Bug][P2] 项目进度忽略AI_DATA_ROOT，读取打包模板而非提示词系统使用的自定义任务 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#87](https://github.com/isWANGBIAO/Vantage/issues/87) | [Bug][P2] 项目进度把Markdown代码块中的复选框示例计为真实任务 | Markdown 批次开发与独立审查中 | — | 围栏/GFM/缩进/代码literal先红后绿；待全套验证和PR |
| [#88](https://github.com/isWANGBIAO/Vantage/issues/88) | [Bug][P2] Excel临时快照仅按微秒命名，并发读取会串用工作簿并互删文件 | 待按根因批次修复 | — | 待记录 |
| [#89](https://github.com/isWANGBIAO/Vantage/issues/89) | [Bug][P2] 提示词仅选中一行时丢弃完整记录，历史区和 Current Day 同时为空 | 待按根因批次修复 | — | 待记录 |
| [#90](https://github.com/isWANGBIAO/Vantage/issues/90) | [Bug][P2] 提示词汇总绕过输入预算，被裁掉的长记录经 latest_values 全量回填 | 待按根因批次修复 | — | 待记录 |
| [#91](https://github.com/isWANGBIAO/Vantage/issues/91) | [Bug][P2] 两轮行动计划只为第一轮计算预算，第二轮追加消息后仍发送超限请求 | 待按根因批次修复 | — | 待记录 |
| [#92](https://github.com/isWANGBIAO/Vantage/issues/92) | [Bug][P2] 采购建议结果缓存被当前分钟污染，未改数据也会重复生成并新增缓存文件 | 待按根因批次修复 | — | 待记录 |
| [#93](https://github.com/isWANGBIAO/Vantage/issues/93) | [Bug][P2] 采购建议重新生成使用旧排除快照，迟到响应重新带回刚打叉的项目 | 待按根因批次修复 | — | 待记录 |
| [#94](https://github.com/isWANGBIAO/Vantage/issues/94) | [Bug][P2] 图表刷新未隔离在途旧任务，迟到错误结果会覆盖刷新后的正常缓存 | 待按根因批次修复 | — | 待记录 |
| [#95](https://github.com/isWANGBIAO/Vantage/issues/95) | [Bug][P2] SSE 显式错误被 DONE 掩盖，失败聊天正文仍落盘并进入后续上下文 | draft 已提交，CI lint 反馈已追加修正 | #143 | cba7d18 / 98bea3e / f007f37 / 510e35e；1863 Python、真实 HTTP→子进程→job→发布10项 |
| [#96](https://github.com/isWANGBIAO/Vantage/issues/96) | [Bug][P2] 未使用的备用 provider 发现失败会阻断健康主 provider 和整个模型目录 | 待按根因批次修复 | — | 待记录 |
| [#97](https://github.com/isWANGBIAO/Vantage/issues/97) | [Bug][P2] GLM/Qwen 参数适配日志读取可缺省字段，合法配置在请求前崩溃并跳过回退 | 待按根因批次修复 | — | 待记录 |
| [#98](https://github.com/isWANGBIAO/Vantage/issues/98) | [Bug][P2] 内置通配模型 profile 永远抢先命中，用户保存的精确模型覆盖完全不生效 | 待按根因批次修复 | — | 待记录 |
| [#99](https://github.com/isWANGBIAO/Vantage/issues/99) | [Bug][P2] 仅指定 model 的聊天不会选择持有该模型的 provider，直接调用默认模型 | 待按根因批次修复 | — | 待记录 |
| [#100](https://github.com/isWANGBIAO/Vantage/issues/100) | [Bug][P2] 刷新并保存模型会丢失 supported_parameters，原可用聊天开始发送不支持的 reasoning_effort | 设置交互与模型能力合同批次开发中 | — | 已分配；未完成验收，不关单 |
| [#101](https://github.com/isWANGBIAO/Vantage/issues/101) | [Bug][P1] 打包冷启动会把损坏但可恢复的 providers.json 无备份覆盖为空配置 | draft 已提交，正式 CI 中 | #142 | 11877f6 / 07e3cbb / e2bb9f8 / 3413f5e；配置97、严格合同124、600前端及真实UI主题回归 |
| [#102](https://github.com/isWANGBIAO/Vantage/issues/102) | [Bug][P2] 打包冷启动删除已保存的 Provider token 限制，使 16K 模型预算膨胀至 215K | draft 已提交，正式 CI 中 | #142 | 11877f6 / 07e3cbb / e2bb9f8 / 3413f5e；配置97、严格合同124、600前端及真实UI主题回归 |
| [#103](https://github.com/isWANGBIAO/Vantage/issues/103) | [Bug][P2] 首次引导返回 422 后仍留下历史副本，改选来源重试成功却保留错误目录数据 | 待按根因批次修复 | — | 待记录 |
| [#104](https://github.com/isWANGBIAO/Vantage/issues/104) | [Bug][P2] 历史迁移静默跳过不可读子目录并标记完成，权限恢复后重试仍不补导 | 待按根因批次修复 | — | 待记录 |
| [#105](https://github.com/isWANGBIAO/Vantage/issues/105) | [Bug][P2] 最新媒体扫描把目录修改时间当成子树上限，同步旧目录后漏掉今天新照片 | 待按根因批次修复 | — | 待记录 |
| [#106](https://github.com/isWANGBIAO/Vantage/issues/106) | [Bug][P2] 存储扫描跳过无权列出的子目录后仍把部分大小展示为完整统计 | 待按根因批次修复 | — | 待记录 |
| [#107](https://github.com/isWANGBIAO/Vantage/issues/107) | [Bug][P2] 输出管道积压时取消行动计划卡在 cancelling，后续无法创建新任务 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#108](https://github.com/isWANGBIAO/Vantage/issues/108) | [Bug][P2] 运行中开启自动生成后首次失败，既有来源基线使后续轮询跳过失败重试 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#109](https://github.com/isWANGBIAO/Vantage/issues/109) | [Bug][P2] 转录超时终止子进程后，已完成转码的WAV副本未被清理 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#110](https://github.com/isWANGBIAO/Vantage/issues/110) | [Bug][P2] [财务] 工作簿不可用被当作正常空表，后端明确给出的缺失文件原因没有显示 | 待按根因批次修复 | — | 待记录 |
| [#111](https://github.com/isWANGBIAO/Vantage/issues/111) | [Bug][P2] [财务] 资产金额全部缺失时，单项为 -- 但资产合计显示确定的 ¥0.00 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#112](https://github.com/isWANGBIAO/Vantage/issues/112) | [Bug][P3] [人脸历史] 相机离线或尚无有效样本时，未知最新分数显示成 0.00 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#113](https://github.com/isWANGBIAO/Vantage/issues/113) | [Bug][P2] Never Stop删除已选资源后保留失效ID，项目所有后续资源勾选持续报错 | 已关闭：main 全部CI和专项验证通过 | #140 | 48e03f7；Never Stop 157/157，本机与 PR CI 通过 |
| [#114](https://github.com/isWANGBIAO/Vantage/issues/114) | [Bug][P2] Never Stop开始/续跑发送的执行指令要求遵循未发布的goal.md草稿 | 用户已决定即时保存生效，统一源和UI实现中 | — | goal.md唯一真源；保存用于下次实际执行，当前轮不中断；无需额外发布 |
| [#115](https://github.com/isWANGBIAO/Vantage/issues/115) | [Bug][P1] 人脸历史旧版数据库被 report/export 并发重复迁移，合法分数永久放大并截断为 100 | 待按根因批次修复 | — | 待记录 |
| [#116](https://github.com/isWANGBIAO/Vantage/issues/116) | [Bug][P2] 并发人脸 Excel 导出共用文件，HTTP 200 下载出现 CRC 损坏或 0 字节 | 待按根因批次修复 | — | 待记录 |
| [#117](https://github.com/isWANGBIAO/Vantage/issues/117) | [Bug][P2] 时间均线按 Excel 物理行计算，同一记录仅重新排序就改变历史趋势 | 待按根因批次修复 | — | 待记录 |
| [#118](https://github.com/isWANGBIAO/Vantage/issues/118) | [Bug][P2] 无日期的体重记录被标为最新测量，并参与图中不可见的平均值计算 | 待按根因批次修复 | — | 待记录 |
| [#119](https://github.com/isWANGBIAO/Vantage/issues/119) | [Bug][P2] 跑步缺失心率被整点删除，曲线跨过缺测日连线而非提示所述断点 | 待按根因批次修复 | — | 待记录 |
| [#120](https://github.com/isWANGBIAO/Vantage/issues/120) | [Bug][P2] 已跳过的时间记录含坏日期时，警告格式化异常使五张正常时间图全部空白 | 待按根因批次修复 | — | 待记录 |
| [#121](https://github.com/isWANGBIAO/Vantage/issues/121) | [Bug][P2] 前端依赖入口文件缺失时同步仍验证通过，重跑启动无法修复构建失败 | 已有 draft 已补修，等待全部 CI | #141 | fd0feb2 / c6cdba8 / 379db80；1832 Python +81子用例、605前端、50专项 |
| [#122](https://github.com/isWANGBIAO/Vantage/issues/122) | [Bug][P2] 前端主 JS 产物丢失后构建缓存仍命中，RUN_DEV 跳过重建继续生产启动 | 已有 draft 已补修，等待全部 CI | #141 | fd0feb2 / c6cdba8 / 379db80；1832 Python +81子用例、605前端、50专项 |
| [#123](https://github.com/isWANGBIAO/Vantage/issues/123) | [Bug][P2] 依赖安装期间编辑 requirements 会认证新要求与旧环境，后续持续错误复用 | 已有 draft 已补修，等待全部 CI | #141 | fd0feb2 / c6cdba8 / 379db80；1832 Python +81子用例、605前端、50专项 |
| [#124](https://github.com/isWANGBIAO/Vantage/issues/124) | [Bug][P2] MCP取消正在读取的事件流时同步关闭socket，阻塞整个异步事件循环 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#125](https://github.com/isWANGBIAO/Vantage/issues/125) | [Bug][P2] CLI导出固定30秒超时，拒绝后端60秒预算内可正常完成的Excel导出 | CLI/MCP/任务与转录生命周期批次开发中 | — | 已分配；未完成验收，不关单 |
| [#126](https://github.com/isWANGBIAO/Vantage/issues/126) | [Bug][P2] [财务] 中文“非必需”被反向归为必须开支，汇总与提示均错误 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#127](https://github.com/isWANGBIAO/Vantage/issues/127) | [Bug][P2] [财务] 日预算折算按两套月天数，同页必须预算124却列出月合计120 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#128](https://github.com/isWANGBIAO/Vantage/issues/128) | [Bug][P2] [财务] 行式资产负债表把流动负债当作负债合计，忽略明确总计7000 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#129](https://github.com/isWANGBIAO/Vantage/issues/129) | [Bug][P2] [财务] 合法工作簿没有Budget或Budget为空时，开销表渲染异常清空整个应用 | draft 已提交，双独立审查及 follow-up 修正 | #144 | 63f4f23 / e6c1582；1841 Python +94子用例、591前端、62财务/绘图 +19子用例 |
| [#130](https://github.com/isWANGBIAO/Vantage/issues/130) | [Bug][P2] 夏令时回拨把两个真实采集小时视为相同时间ID，照片被跳过或重启后覆盖 | 待按根因批次修复 | — | 待记录 |
| [#131](https://github.com/isWANGBIAO/Vantage/issues/131) | [Bug][P2] Time.xlsx混用两种各自支持的ISO日期表示时，整个行动计划在模型请求前失败 | 待按根因批次修复 | — | 待记录 |
| [#132](https://github.com/isWANGBIAO/Vantage/issues/132) | [Bug][P2] 摄像头 MJPEG 连接断开后仍显示 Live，健康状态轮询无法重新打开画面 | 待按根因批次修复 | — | 待记录 |
| [#133](https://github.com/isWANGBIAO/Vantage/issues/133) | [Bug][P2] 行动计划作业丢失后的保存结果首读失败，当前窗口无法自行恢复完整计划 | 待按根因批次修复 | — | 待记录 |
| [#134](https://github.com/isWANGBIAO/Vantage/issues/134) | [Bug][P2] 人脸分析断线后返回 idle，当前窗口持续卡在分析中且无法重新分析 | 待按根因批次修复 | — | 待记录 |
| [#135](https://github.com/isWANGBIAO/Vantage/issues/135) | [Bug][P2] 行动计划清洗器压平合法嵌套列表，并破坏保存正文的代码块缩进 | Markdown 批次开发与独立审查中 | — | 围栏/GFM/缩进/代码literal先红后绿；待全套验证和PR |
| [#136](https://github.com/isWANGBIAO/Vantage/issues/136) | [Bug][P2] 合法GFM任务列表被项目进度漏算，未完成项目显示100%完成 | Markdown 批次开发与独立审查中 | — | 围栏/GFM/缩进/代码literal先红后绿；待全套验证和PR |
| [#137](https://github.com/isWANGBIAO/Vantage/issues/137) | [Bug][P2] 系统提示词的除夕提醒跨年漏报，大月年份又提前一天 | 待按根因批次修复 | — | 待记录 |

## 验证与整合注意

- #141 初轮 macOS 的合法条件 exports 被误拒、Python Windows 8.3路径 fixture 差异已修，未削弱生产校验。
- #142 原有生产 UI 主题竞态真实复现并修复（#43），不是重跑掩盖失败。
- #143 CI lint 的闭包绑定反馈已追加提交修正，等待新的 head 检查。
- #144 两次独立审查发现的无日期金额误猜日期、紧凑日期、旧值标新日期、混合缺失总额均补先红后绿测试，未带着阻塞意见合并。
- 旧 main 的 Never Stop 进程恢复测试曾超时；#140 本机157项和 PR CI通过，合并后当前 frontend已通过。继续观察最终 main CI，不单纯扩大超时掩盖竞态。

