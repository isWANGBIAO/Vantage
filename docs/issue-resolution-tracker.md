# 开放 Issue 修复与验证台账

更新时间：2026-10-22。范围以GitHub实际开放项为准：初始95项，已凭精确main提交及专项证据关闭9项，目前86项仍开放。已合并#140/#141/#146；其余按根因完成修复后统一集成。草稿、合成测试通过和PR CI均不替代最终main提交核验。

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
| [#43](https://github.com/isWANGBIAO/Vantage/issues/43) | [Bug][P2] 切换主题触发表单重载，保存时写回旧主题并丢弃未保存修改 | 已纳入集成，待最终CI与main核验 | #142 → 集成PR | 3413f5e；严格设置124、配置97、真实UI主题回归；回归：`tests/test_provider_bootstrap_limits.py; tests/test_settings_integrity.py; providerConfigSafety.test.js` |
| [#44](https://github.com/isWANGBIAO/Vantage/issues/44) | [Bug] [P1] 空聊天消息误入行动计划生成并覆盖现有聊天上下文 | 已纳入集成，待最终CI与main核验 | #143 → 集成PR | 510e35e；1863 Python；真实HTTP→子进程→job→发布10项；回归：`tests/test_chat_input_boundaries.py; tests/test_ai_stream_failures.py; tests/test_ai_stream_end_to_end.py` |
| [#45](https://github.com/isWANGBIAO/Vantage/issues/45) | [Bug] [P2] 聊天内容为 --help 等单个连字符开头文本时被误当作子进程参数 | 已纳入集成，待最终CI与main核验 | #143 → 集成PR | 510e35e；1863 Python；真实HTTP→子进程→job→发布10项；回归：`tests/test_chat_input_boundaries.py; tests/test_ai_stream_failures.py; tests/test_ai_stream_end_to_end.py` |
| [#46](https://github.com/isWANGBIAO/Vantage/issues/46) | [Bug] [P2] CLI/MCP 将报错或缺少完成事件的聊天流标记为成功 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_client_stream_outcomes.py` |
| [#47](https://github.com/isWANGBIAO/Vantage/issues/47) | [Bug] [P2] 设置 HTTP 写入未执行公开 schema，错误类型会启用自动生成或返回 500 | 已纳入集成，待最终CI与main核验 | #142 → 集成PR | 3413f5e；严格设置124、配置97、真实UI主题回归；回归：`tests/test_provider_bootstrap_limits.py; tests/test_settings_integrity.py; providerConfigSafety.test.js` |
| [#48](https://github.com/isWANGBIAO/Vantage/issues/48) | [Bug][P1] 行动计划流截断后即使重试成功，仍被先前的错误事件永久判为失败 | 已纳入集成，待最终CI与main核验 | #143 → 集成PR | 510e35e；1863 Python；真实HTTP→子进程→job→发布10项；回归：`tests/test_chat_input_boundaries.py; tests/test_ai_stream_failures.py; tests/test_ai_stream_end_to_end.py` |
| [#49](https://github.com/isWANGBIAO/Vantage/issues/49) | [Bug][P1] 12000 字符中文提示词分块超过子进程行缓冲上限，导致行动计划失败 | 已纳入集成，待最终CI与main核验 | #143 → 集成PR | 510e35e；1863 Python；真实HTTP→子进程→job→发布10项；回归：`tests/test_chat_input_boundaries.py; tests/test_ai_stream_failures.py; tests/test_ai_stream_end_to_end.py` |
| [#50](https://github.com/isWANGBIAO/Vantage/issues/50) | [Bug][P2] 非空聊天请求遇到模型空回复时仍返回 done=true，用户消息未保存 | 已纳入集成，待最终CI与main核验 | #143 → 集成PR | 510e35e；1863 Python；真实HTTP→子进程→job→发布10项；回归：`tests/test_chat_input_boundaries.py; tests/test_ai_stream_failures.py; tests/test_ai_stream_end_to_end.py` |
| [#51](https://github.com/isWANGBIAO/Vantage/issues/51) | [Bug][P2] [首次引导] 跳过聊天后返回上一步，Provider 表单无法再次编辑 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#52](https://github.com/isWANGBIAO/Vantage/issues/52) | [Bug][P2] [导航] 返回首次打开的无 hash 地址时仍停留在后一个页面 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#53](https://github.com/isWANGBIAO/Vantage/issues/53) | [Bug][P2] [数据导入] Mi Fitness 与 Zepp 只识别写死的历史导出文件名，正常新导出被静默忽略 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#54](https://github.com/isWANGBIAO/Vantage/issues/54) | [Bug][P2] [财务] 摘要按工作表末行取值，倒序记录会把旧余额标为最新日期 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#55](https://github.com/isWANGBIAO/Vantage/issues/55) | [Bug][P2] [财务] 无实际记录时预测数据仍进入实际资产摘要和现金覆盖建议 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#56](https://github.com/isWANGBIAO/Vantage/issues/56) | [Bug][P2] [人脸历史] 单个零字节 JPG 使整批分析中断且后续照片无法处理 | 已纳入集成，待最终CI与main核验 | #150 → 集成PR | 3ea5767；89 Python/2子用例；独立71+10真实DB/HTTP/DST；回归：`tests/test_face_history_integrity.py; tests/test_take_photo.py` |
| [#57](https://github.com/isWANGBIAO/Vantage/issues/57) | [Bug][P2] 行动计划来源指纹遗漏实际读取的 Prompt_System.md，修改后调度器不重新生成 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#58](https://github.com/isWANGBIAO/Vantage/issues/58) | [Bug][P2] 跨午夜生成的昨日输入被按完成日期标为今日计划，绕过日期校验并推进调度基线 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#59](https://github.com/isWANGBIAO/Vantage/issues/59) | [Bug][P2] [设置] 模型发现请求的迟到响应会重新创建已删除的 Provider | 已纳入集成，待最终CI与main核验 | #147 → 集成PR | f443028；1861 Python、602前端、真实UI；整数路由复核；回归：`tests/test_settings_integrity.py; scripts/smoke-unified-ui.cjs` |
| [#60](https://github.com/isWANGBIAO/Vantage/issues/60) | [Bug][P2] [无障碍] AI Provider 的五个关键输入控件没有可访问名称 | 已纳入集成，待最终CI与main核验 | #147 → 集成PR | f443028；1861 Python、602前端、真实UI；整数路由复核；回归：`tests/test_settings_integrity.py; scripts/smoke-unified-ui.cjs` |
| [#61](https://github.com/isWANGBIAO/Vantage/issues/61) | [Bug][P2] [设置] 语音“跟随 AI Provider”显示上次浏览的 Provider，与实际使用的默认 Provider 不一致 | 已纳入集成，待最终CI与main核验 | #147 → 集成PR | f443028；1861 Python、602前端、真实UI；整数路由复核；回归：`tests/test_settings_integrity.py; scripts/smoke-unified-ui.cjs` |
| [#62](https://github.com/isWANGBIAO/Vantage/issues/62) | [Bug][P1] [设置] 重命名 Provider 路由会无提示删除已保存密钥，并可能切换到另一家服务 | 已纳入集成，待最终CI与main核验 | #147 → 集成PR | f443028；1861 Python、602前端、真实UI；整数路由复核；回归：`tests/test_settings_integrity.py; scripts/smoke-unified-ui.cjs` |
| [#63](https://github.com/isWANGBIAO/Vantage/issues/63) | [Bug][P2] 语音转录成功响应只保留第一行，静默丢弃后续文本 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_audio_protocol_integrity.py` |
| [#64](https://github.com/isWANGBIAO/Vantage/issues/64) | [Bug][P2] 转录上传读取失败或被取消时，临时音频文件未清理 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_transcription_workspace.py` |
| [#65](https://github.com/isWANGBIAO/Vantage/issues/65) | [Bug][P3] 大写扩展名 MP3/FLAC/M4A 被错误标记为 audio/wav 上传 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_audio_protocol_integrity.py` |
| [#66](https://github.com/isWANGBIAO/Vantage/issues/66) | [Bug][P2] [财务预测] 未补零的文本日期按字典序滚动余额，10 月资金被提前计入 2 月 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#67](https://github.com/isWANGBIAO/Vantage/issues/67) | [Bug][P2] [跑步导入] 一行合法 JSON 非对象值可终止整个 Mi Fitness 导入 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#68](https://github.com/isWANGBIAO/Vantage/issues/68) | [Bug][P2] [人脸趋势] 日聚合把本地日期当 UTC，负时区周/月图坐标轴提前一天 | 已纳入集成，待最终CI与main核验 | #150 → 集成PR | 3ea5767；89 Python/2子用例；独立71+10真实DB/HTTP/DST；回归：`tests/test_face_history_integrity.py; tests/test_take_photo.py` |
| [#69](https://github.com/isWANGBIAO/Vantage/issues/69) | [Bug][P2] [财务接口] Excel 中的 inf/-inf 泄漏到 prompt_payload，整个资产负债表返回 500 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#70](https://github.com/isWANGBIAO/Vantage/issues/70) | [Bug][P2] [时间统计] 时长正则拒绝 30分，却把负数和小数截成正常小时数 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#71](https://github.com/isWANGBIAO/Vantage/issues/71) | [Bug][P2] [财务] 字符清洗篡改科学计数法与负号，1e3 被算成 13、负资产变正资产 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#72](https://github.com/isWANGBIAO/Vantage/issues/72) | [Bug][P2] AI_Prediction独立脚本的次日食物关联依赖同日行序 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#73](https://github.com/isWANGBIAO/Vantage/issues/73) | [Bug][P2] Never Stop新增/删除项目持久化失败后仍改变内存，后续操作会静默提交失败修改 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#74](https://github.com/isWANGBIAO/Vantage/issues/74) | [Bug] [P2] 用量统计把未上报 usage 的正常回复当成 0 token，导致总量和吞吐误导 | 已纳入集成，待最终CI与main核验 | #157 → 集成PR | a62cc45 / 4be61b4 / 2e7ea80；1851 Python/81子用例、607前端；缺失/零值与DST19新回归；回归：`tests/test_usage_integrity.py; UsagePanel.test.js`  追加回归：`tests/test_action_plan_usage_fidelity.py; tests/test_model_usage_integration.py; ChatInterface.test.js` |
| [#75](https://github.com/isWANGBIAO/Vantage/issues/75) | [Bug] [P2] 夏令时/时区偏移变化会让启动修复误删仍在进行的模型调用 | 已纳入集成，待最终CI与main核验 | #157 → 集成PR | a62cc45；1851 Python/81子用例、607前端；缺失/零值与DST19新回归；回归：`tests/test_usage_integrity.py; UsagePanel.test.js` |
| [#76](https://github.com/isWANGBIAO/Vantage/issues/76) | [Bug][P2] --skip-build 会删除已有后端打包产物，随后因缺失文件失败 | 已纳入集成，待最终CI与main核验 | #145 → 集成PR | f182ba0 / 2ff2057 / c4c17d1；43包装Python、14真实缓存Node；中断发布与assets红绿；回归：`tests/test_backend_build_reuse_safety.py; backendLifecycle.test.js; frontendBuildCache.test.cjs` |
| [#77](https://github.com/isWANGBIAO/Vantage/issues/77) | [Bug][P2] skip-build 将新源码指纹写入未重建的旧产物，后续错误命中缓存 | 已纳入集成，待最终CI与main核验 | #145 → 集成PR | f182ba0 / 2ff2057 / c4c17d1；43包装Python、14真实缓存Node；中断发布与assets红绿；回归：`tests/test_backend_build_reuse_safety.py; backendLifecycle.test.js; frontendBuildCache.test.cjs` |
| [#78](https://github.com/isWANGBIAO/Vantage/issues/78) | [Bug][P2] 后端尚未 ready 时退出桌面应用，已启动的后台进程不会被终止 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#79](https://github.com/isWANGBIAO/Vantage/issues/79) | [Bug][P2] 后端 spawn 异步失败未拒绝启动 Promise，错误只进入全局日志并继续等待 | 已纳入集成，待最终CI与main核验 | #145 → 集成PR | f182ba0 / 2ff2057 / c4c17d1；43包装Python、14真实缓存Node；中断发布与assets红绿；回归：`tests/test_backend_build_reuse_safety.py; backendLifecycle.test.js; frontendBuildCache.test.cjs` |
| [#80](https://github.com/isWANGBIAO/Vantage/issues/80) | [Bug][P2] 状态探测遇到截断 HTTP 响应会永久 pending，启动超时失效 | 已纳入集成，待最终CI与main核验 | #145 → 集成PR | f182ba0 / 2ff2057 / c4c17d1；43包装Python、14真实缓存Node；中断发布与assets红绿；回归：`tests/test_backend_build_reuse_safety.py; backendLifecycle.test.js; frontendBuildCache.test.cjs` |
| [#81](https://github.com/isWANGBIAO/Vantage/issues/81) | [Bug][P2] 打包缓存指纹写入中断后，下次 reuse 构建直接崩溃而不重建 | 已纳入集成，待最终CI与main核验 | #145 → 集成PR | f182ba0 / 2ff2057 / c4c17d1；43包装Python、14真实缓存Node；中断发布与assets红绿；回归：`tests/test_backend_build_reuse_safety.py; backendLifecycle.test.js; frontendBuildCache.test.cjs` |
| [#82](https://github.com/isWANGBIAO/Vantage/issues/82) | [Bug][P2] 相机停止产出新帧后，实时人脸接口仍把旧图重新标为当前测量 | 已纳入集成，待最终CI与main核验 | #153 → 集成PR | b311af0；1849 Python；独立61/2子用例、真实异步JPEG保存；回归：`tests/test_camera_observation_lifecycle.py; tests/test_face_live_endpoint.py` |
| [#83](https://github.com/isWANGBIAO/Vantage/issues/83) | [Bug][P2] Presence 推理只在开始校验帧，过期或已被替换的结果仍保存并覆盖实时检测框 | 已纳入集成，待最终CI与main核验 | #153 → 集成PR | b311af0；1849 Python；独立61/2子用例、真实异步JPEG保存；回归：`tests/test_camera_observation_lifecycle.py; tests/test_face_live_endpoint.py` |
| [#84](https://github.com/isWANGBIAO/Vantage/issues/84) | [Bug][P2] [采购建议] 单条恢复排除项后没有放回推荐列表，页面刷新按钮也无法恢复显示 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#85](https://github.com/isWANGBIAO/Vantage/issues/85) | [Bug][P2] [仪表盘] AQI读取失败后仍把上次空气质量显示为当前值，没有过期或不可用提示 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#86](https://github.com/isWANGBIAO/Vantage/issues/86) | [Bug][P2] 项目进度忽略AI_DATA_ROOT，读取打包模板而非提示词系统使用的自定义任务 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#87](https://github.com/isWANGBIAO/Vantage/issues/87) | [Bug][P2] 项目进度把Markdown代码块中的复选框示例计为真实任务 | 已合并，等待main精确提交CI | #146 | eb760d8；1834 Python、589前端、双macOS与CodeQL全绿；回归：`tests/test_markdown_contracts.py; markdownPreservation.test.js` |
| [#88](https://github.com/isWANGBIAO/Vantage/issues/88) | [Bug][P2] Excel临时快照仅按微秒命名，并发读取会串用工作簿并互删文件 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#89](https://github.com/isWANGBIAO/Vantage/issues/89) | [Bug][P2] 提示词仅选中一行时丢弃完整记录，历史区和 Current Day 同时为空 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#90](https://github.com/isWANGBIAO/Vantage/issues/90) | [Bug][P2] 提示词汇总绕过输入预算，被裁掉的长记录经 latest_values 全量回填 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#91](https://github.com/isWANGBIAO/Vantage/issues/91) | [Bug][P2] 两轮行动计划只为第一轮计算预算，第二轮追加消息后仍发送超限请求 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#92](https://github.com/isWANGBIAO/Vantage/issues/92) | [Bug][P2] 采购建议结果缓存被当前分钟污染，未改数据也会重复生成并新增缓存文件 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`tests/test_purchase_cache_consistency.py` |
| [#93](https://github.com/isWANGBIAO/Vantage/issues/93) | [Bug][P2] 采购建议重新生成使用旧排除快照，迟到响应重新带回刚打叉的项目 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`tests/test_purchase_cache_consistency.py` |
| [#94](https://github.com/isWANGBIAO/Vantage/issues/94) | [Bug][P2] 图表刷新未隔离在途旧任务，迟到错误结果会覆盖刷新后的正常缓存 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`tests/test_plot_refresh_generation.py` |
| [#95](https://github.com/isWANGBIAO/Vantage/issues/95) | [Bug][P2] SSE 显式错误被 DONE 掩盖，失败聊天正文仍落盘并进入后续上下文 | 已纳入集成，待最终CI与main核验 | #143 → 集成PR | 510e35e；1863 Python；真实HTTP→子进程→job→发布10项；回归：`tests/test_chat_input_boundaries.py; tests/test_ai_stream_failures.py; tests/test_ai_stream_end_to_end.py` |
| [#96](https://github.com/isWANGBIAO/Vantage/issues/96) | [Bug][P2] 未使用的备用 provider 发现失败会阻断健康主 provider 和整个模型目录 | 已纳入集成，待最终CI与main核验 | #152 → 集成PR | 841d4e5；1850 Python；独立69真实loopback模型/目录/路由；回归：`tests/test_model_resolution_boundaries.py` |
| [#97](https://github.com/isWANGBIAO/Vantage/issues/97) | [Bug][P2] GLM/Qwen 参数适配日志读取可缺省字段，合法配置在请求前崩溃并跳过回退 | 已纳入集成，待最终CI与main核验 | #152 → 集成PR | 841d4e5；1850 Python；独立69真实loopback模型/目录/路由；回归：`tests/test_model_resolution_boundaries.py` |
| [#98](https://github.com/isWANGBIAO/Vantage/issues/98) | [Bug][P2] 内置通配模型 profile 永远抢先命中，用户保存的精确模型覆盖完全不生效 | 已纳入集成，待最终CI与main核验 | #152 → 集成PR | 841d4e5；1850 Python；独立69真实loopback模型/目录/路由；回归：`tests/test_model_resolution_boundaries.py` |
| [#99](https://github.com/isWANGBIAO/Vantage/issues/99) | [Bug][P2] 仅指定 model 的聊天不会选择持有该模型的 provider，直接调用默认模型 | 已纳入集成，待最终CI与main核验 | #152 → 集成PR | 841d4e5；1850 Python；独立69真实loopback模型/目录/路由；回归：`tests/test_model_resolution_boundaries.py` |
| [#100](https://github.com/isWANGBIAO/Vantage/issues/100) | [Bug][P2] 刷新并保存模型会丢失 supported_parameters，原可用聊天开始发送不支持的 reasoning_effort | 已纳入集成，待最终CI与main核验 | #147 → 集成PR | f443028；1861 Python、602前端、真实UI；整数路由复核；回归：`tests/test_settings_integrity.py; scripts/smoke-unified-ui.cjs` |
| [#101](https://github.com/isWANGBIAO/Vantage/issues/101) | [Bug][P1] 打包冷启动会把损坏但可恢复的 providers.json 无备份覆盖为空配置 | 已纳入集成，待最终CI与main核验 | #142 → 集成PR | 3413f5e；严格设置124、配置97、真实UI主题回归；回归：`tests/test_provider_bootstrap_limits.py; tests/test_settings_integrity.py; providerConfigSafety.test.js` |
| [#102](https://github.com/isWANGBIAO/Vantage/issues/102) | [Bug][P2] 打包冷启动删除已保存的 Provider token 限制，使 16K 模型预算膨胀至 215K | 已纳入集成，待最终CI与main核验 | #142 → 集成PR | 3413f5e；严格设置124、配置97、真实UI主题回归；回归：`tests/test_provider_bootstrap_limits.py; tests/test_settings_integrity.py; providerConfigSafety.test.js` |
| [#103](https://github.com/isWANGBIAO/Vantage/issues/103) | [Bug][P2] 首次引导返回 422 后仍留下历史副本，改选来源重试成功却保留错误目录数据 | 已纳入集成，独立复核通过，待main核验 | #156 → 集成PR | 93db67d（含安全重做）；1854 Python/81子用例；独立86；回归：`tests/test_settings_automation_endpoint.py; tests/test_media_scan_integrity.py; tests/test_storage_stats.py` |
| [#104](https://github.com/isWANGBIAO/Vantage/issues/104) | [Bug][P2] 历史迁移静默跳过不可读子目录并标记完成，权限恢复后重试仍不补导 | 已纳入集成，独立复核通过，待main核验 | #156 → 集成PR | 93db67d（含安全重做）；1854 Python/81子用例；独立86；回归：`tests/test_settings_automation_endpoint.py; tests/test_media_scan_integrity.py; tests/test_storage_stats.py` |
| [#105](https://github.com/isWANGBIAO/Vantage/issues/105) | [Bug][P2] 最新媒体扫描把目录修改时间当成子树上限，同步旧目录后漏掉今天新照片 | 已纳入集成，独立复核通过，待main核验 | #156 → 集成PR | 93db67d（含安全重做）；1854 Python/81子用例；独立86；回归：`tests/test_media_scan_integrity.py` |
| [#106](https://github.com/isWANGBIAO/Vantage/issues/106) | [Bug][P2] 存储扫描跳过无权列出的子目录后仍把部分大小展示为完整统计 | 已纳入集成，独立复核通过，待main核验 | #156 → 集成PR | 93db67d（含安全重做）；1854 Python/81子用例；独立86；回归：`tests/test_media_scan_integrity.py; tests/test_storage_stats.py` |
| [#107](https://github.com/isWANGBIAO/Vantage/issues/107) | [Bug][P2] 输出管道积压时取消行动计划卡在 cancelling，后续无法创建新任务 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_backend_subprocess_cleanup.py` |
| [#108](https://github.com/isWANGBIAO/Vantage/issues/108) | [Bug][P2] 运行中开启自动生成后首次失败，既有来源基线使后续轮询跳过失败重试 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_action_plan_scheduler.py` |
| [#109](https://github.com/isWANGBIAO/Vantage/issues/109) | [Bug][P2] 转录超时终止子进程后，已完成转码的WAV副本未被清理 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_transcription_workspace.py` |
| [#110](https://github.com/isWANGBIAO/Vantage/issues/110) | [Bug][P2] [财务] 工作簿不可用被当作正常空表，后端明确给出的缺失文件原因没有显示 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#111](https://github.com/isWANGBIAO/Vantage/issues/111) | [Bug][P2] [财务] 资产金额全部缺失时，单项为 -- 但资产合计显示确定的 ¥0.00 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#112](https://github.com/isWANGBIAO/Vantage/issues/112) | [Bug][P3] [人脸历史] 相机离线或尚无有效样本时，未知最新分数显示成 0.00 | 已关闭：当前源码与专项验证成立 | — | 19来源/项目Python、Never Stop157、后台启动11、faceLocalSettings5（含未知与零值） |
| [#113](https://github.com/isWANGBIAO/Vantage/issues/113) | [Bug][P2] Never Stop删除已选资源后保留失效ID，项目所有后续资源勾选持续报错 | 已关闭：main 全部CI和专项验证通过 | #140 | 48e03f7；Never Stop 157/157，本机与 PR CI 通过 |
| [#114](https://github.com/isWANGBIAO/Vantage/issues/114) | [Bug][P2] Never Stop开始/续跑发送的执行指令要求遵循未发布的goal.md草稿 | 已纳入集成，待最终CI与main核验 | #148 → 集成PR | bf9bc40 / d39885f；保存即下轮生效；171/171默认并行多次通过；回归：`never-stop/core/live-goals.test.cjs; never-stop/core/runner.test.cjs; never-stop/ui/state.test.mjs` |
| [#115](https://github.com/isWANGBIAO/Vantage/issues/115) | [Bug][P1] 人脸历史旧版数据库被 report/export 并发重复迁移，合法分数永久放大并截断为 100 | 已纳入集成，待最终CI与main核验 | #150 → 集成PR | 3ea5767；89 Python/2子用例；独立71+10真实DB/HTTP/DST；回归：`tests/test_face_history_integrity.py; tests/test_take_photo.py` |
| [#116](https://github.com/isWANGBIAO/Vantage/issues/116) | [Bug][P2] 并发人脸 Excel 导出共用文件，HTTP 200 下载出现 CRC 损坏或 0 字节 | 已纳入集成，待最终CI与main核验 | #150 → 集成PR | 3ea5767；89 Python/2子用例；独立71+10真实DB/HTTP/DST；回归：`tests/test_face_history_integrity.py; tests/test_take_photo.py` |
| [#117](https://github.com/isWANGBIAO/Vantage/issues/117) | [Bug][P2] 时间均线按 Excel 物理行计算，同一记录仅重新排序就改变历史趋势 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#118](https://github.com/isWANGBIAO/Vantage/issues/118) | [Bug][P2] 无日期的体重记录被标为最新测量，并参与图中不可见的平均值计算 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#119](https://github.com/isWANGBIAO/Vantage/issues/119) | [Bug][P2] 跑步缺失心率被整点删除，曲线跨过缺测日连线而非提示所述断点 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#120](https://github.com/isWANGBIAO/Vantage/issues/120) | [Bug][P2] 已跳过的时间记录含坏日期时，警告格式化异常使五张正常时间图全部空白 | 已纳入集成，待最终CI与main核验 | #154 → 集成PR | 231baea；1870 Python/98子用例、611前端；独立30+真实SVG1；回归：`tests/test_plot_input_contracts.py; runningGapRendering.test.js` |
| [#121](https://github.com/isWANGBIAO/Vantage/issues/121) | [Bug][P2] 前端依赖入口文件缺失时同步仍验证通过，重跑启动无法修复构建失败 | 已关闭：精确main提交全部CI通过 | #141 | f45ece3；PR全部CI通过，精确main CI 39715077572、CodeQL 39715077581全绿；回归：`tests/test_sync_backend_runtime_environment.py; src/frontendDependencySync.test.js; frontendBuildCache.test.cjs` |
| [#122](https://github.com/isWANGBIAO/Vantage/issues/122) | [Bug][P2] 前端主 JS 产物丢失后构建缓存仍命中，RUN_DEV 跳过重建继续生产启动 | 已关闭：精确main提交全部CI通过 | #141 | f45ece3；PR全部CI通过，精确main CI 39715077572、CodeQL 39715077581全绿；回归：`tests/test_sync_backend_runtime_environment.py; src/frontendDependencySync.test.js; frontendBuildCache.test.cjs` |
| [#123](https://github.com/isWANGBIAO/Vantage/issues/123) | [Bug][P2] 依赖安装期间编辑 requirements 会认证新要求与旧环境，后续持续错误复用 | 已关闭：精确main提交全部CI通过 | #141 | f45ece3；PR全部CI通过，精确main CI 39715077572、CodeQL 39715077581全绿；回归：`tests/test_sync_backend_runtime_environment.py; src/frontendDependencySync.test.js; frontendBuildCache.test.cjs` |
| [#124](https://github.com/isWANGBIAO/Vantage/issues/124) | [Bug][P2] MCP取消正在读取的事件流时同步关闭socket，阻塞整个异步事件循环 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_mcp_socket_cancellation.py` |
| [#125](https://github.com/isWANGBIAO/Vantage/issues/125) | [Bug][P2] CLI导出固定30秒超时，拒绝后端60秒预算内可正常完成的Excel导出 | 已纳入集成，待最终CI与main核验 | #149 → 集成PR | 606dcc6；1893 Python；独立34项真实socket/子进程/音频/31秒导出验证；回归：`tests/test_export_client_budget.py` |
| [#126](https://github.com/isWANGBIAO/Vantage/issues/126) | [Bug][P2] [财务] 中文“非必需”被反向归为必须开支，汇总与提示均错误 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#127](https://github.com/isWANGBIAO/Vantage/issues/127) | [Bug][P2] [财务] 日预算折算按两套月天数，同页必须预算124却列出月合计120 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#128](https://github.com/isWANGBIAO/Vantage/issues/128) | [Bug][P2] [财务] 行式资产负债表把流动负债当作负债合计，忽略明确总计7000 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#129](https://github.com/isWANGBIAO/Vantage/issues/129) | [Bug][P2] [财务] 合法工作簿没有Budget或Budget为空时，开销表渲染异常清空整个应用 | 已纳入集成，待最终CI与main核验 | #144 → 集成PR | e6c1582；1841 Python/94子用例，591前端；双独立审查；回归：`tests/test_finance_integrity_regressions.py; expenseIntegrity.test.js` |
| [#130](https://github.com/isWANGBIAO/Vantage/issues/130) | [Bug][P2] 夏令时回拨把两个真实采集小时视为相同时间ID，照片被跳过或重启后覆盖 | 已纳入集成，待最终CI与main核验 | #150 → 集成PR | 3ea5767；89 Python/2子用例；独立71+10真实DB/HTTP/DST；回归：`tests/test_face_history_integrity.py; tests/test_take_photo.py` |
| [#131](https://github.com/isWANGBIAO/Vantage/issues/131) | [Bug][P2] Time.xlsx混用两种各自支持的ISO日期表示时，整个行动计划在模型请求前失败 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |
| [#132](https://github.com/isWANGBIAO/Vantage/issues/132) | [Bug][P2] 摄像头 MJPEG 连接断开后仍显示 Live，健康状态轮询无法重新打开画面 | 已纳入集成，真实TCP/生产UI验收通过 | #155 → 集成PR | 7955f79 / 58f7188；真实断流、隐藏清理、queued→idle；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#133](https://github.com/isWANGBIAO/Vantage/issues/133) | [Bug][P2] 行动计划作业丢失后的保存结果首读失败，当前窗口无法自行恢复完整计划 | 已纳入集成，待最终CI与main核验 | #155 → 集成PR | 104dadf；1841 Python、606前端、8页真实Electron；最终UI补验中；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#134](https://github.com/isWANGBIAO/Vantage/issues/134) | [Bug][P2] 人脸分析断线后返回 idle，当前窗口持续卡在分析中且无法重新分析 | 已纳入集成，真实TCP/生产UI验收通过 | #155 → 集成PR | 7955f79 / 58f7188；真实断流、隐藏清理、queued→idle；回归：`scripts/smoke-unified-ui.cjs; tests/test_purchase_cache_consistency.py; tests/test_plot_refresh_generation.py` |
| [#135](https://github.com/isWANGBIAO/Vantage/issues/135) | [Bug][P2] 行动计划清洗器压平合法嵌套列表，并破坏保存正文的代码块缩进 | 已合并，等待main精确提交CI | #146 | eb760d8；1834 Python、589前端、双macOS与CodeQL全绿；回归：`tests/test_markdown_contracts.py; markdownPreservation.test.js` |
| [#136](https://github.com/isWANGBIAO/Vantage/issues/136) | [Bug][P2] 合法GFM任务列表被项目进度漏算，未完成项目显示100%完成 | 已合并，等待main精确提交CI | #146 | eb760d8；1834 Python、589前端、双macOS与CodeQL全绿；回归：`tests/test_markdown_contracts.py; markdownPreservation.test.js` |
| [#137](https://github.com/isWANGBIAO/Vantage/issues/137) | [Bug][P2] 系统提示词的除夕提醒跨年漏报，大月年份又提前一天 | 已纳入集成，待最终CI与main核验 | #151 → 集成PR | 70ff119；1858 Python/94子用例；真实xlsx→main预算/午夜保护；回归：`tests/test_data_input_contracts.py; tests/test_action_plan_complete_budget.py` |

## 验证与整合注意

- #141 初轮 macOS 的合法条件 exports 被误拒、Python Windows 8.3路径 fixture 差异已修，未削弱生产校验。
- #142 原有生产 UI 主题竞态真实复现并修复（#43），不是重跑掩盖失败。
- #143 CI lint 的闭包绑定反馈已追加提交修正，等待新的 head 检查。
- #144 两次独立审查发现的无日期金额误猜日期、紧凑日期、旧值标新日期、混合缺失总额均补先红后绿测试，未带着阻塞意见合并。
- 旧 main 的 Never Stop 进程恢复测试曾超时；#140 本机157项和 PR CI通过，合并后当前 frontend已通过。继续观察最终 main CI，不单纯扩大超时掩盖竞态。



## 统一集成策略（PR #158）

各批提交正常合并到 `feature/issue-integration`，保留逐项修复与测试链。最终集成PR先draft，独立复核及全量测试/全部必要CI通过后才ready并正常合并main；原批次draft仅在确认其修复已包含后标为superseded。只取消旧head的重复CI，不改检查、不强推、不提前关闭issue。最终再核对远端main实际SHA与同SHA CI，逐项贴证据关单。



## 复验入口

Python路径从仓库根运行 `python -m pytest -q <测试路径>`。表内简写的前端测试位于 `src/webapp/src/components/` 或 `src/webapp/src/utils/`；用 `npm --prefix src/webapp test` 统一运行。Never Stop 用 `npm --prefix src/webapp run never-stop:test`。真实生产UI需先 `npm --prefix src/webapp run build`，再运行 `npm --prefix src/webapp run test:electron-ui`，不接触真实硬件或私人配置。

最终集成本地验收：Python **2094通过 / 16项POSIX专用跳过 / 101子测试通过**；Ruff通过；前端 **649通过**、lint/build通过；Never Stop默认并行 **171/171**；真实Electron协议与8页生产React **381合成请求 / 0渲染错误**。独立交叉复核117项Python和17项用量界面测试通过。此为合并前快照；最终CI、main实际SHA和逐项关闭状态以PR #158及各issue证据为准，不能把本地通过当成远端已合并。

依赖边界：本次安装依赖时 npm audit 仍报告21项既有依赖告警（10中危、11高危，0严重）。它们不是当前95项issue的验收证据，本轮未自动进行破坏性大版本升级，不能据此声称依赖已无漏洞。



## 集成复核补充

- 部分/非法usage在重试和两轮聚合时丢失完整性：先7项对抗失败，再统一严格归一化；未知计数不补零，统计异常不阻止正常正文保存。
- 仅输出速率已知而总量未知的样本保留为有效输出点，未知总速率保持断点；Chat未知值与真实0分开显示，初始计时不伪造token。
- 新增3项真实CLI/HTTP/DTO交互回归，模型别名/route metadata、精确profile与两轮nullable统计均验证；独立117项Python及17项前端用量测试通过。
- Windows十轮进程测试逐轮验证后，默认并行171项多次全绿；生产退避、进程清理与所有权策略均未削弱。
- 一次包装验证命令最初使用了不存在的测试文件名，没有执行任何测试；改用实际存在的包装/缓存测试后43项通过，首次失败不计作验证证据。
- 本机完整Python中的16项跳过均为POSIX专用语义；云端仍要求macOS两个架构的真实打包运行检查通过，不能把Windows结果冒充macOS全量测试。

