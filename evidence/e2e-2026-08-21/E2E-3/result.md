# E2E-3 未知领域（16S）结果：绿

房间 e2e-20260821-16s-unknown-domain（3a59db58d3344432a1fe7eb1df51c14c）。
发言：「执行肠道菌群 16S rRNA 扩增子群落分析，输入 gut_16S_R1.fastq.gz…」+ context_refs。

结果（room_events.json）：
- 路由未识别 16S 领域专家 → 立项卡 flow_label=「通用分析（未识别到领域专家，回退通用代码助手）」、
  confidence=ambiguous、lead_planner=agent-code、route_path=overdrive —— **显式 fallback 文案**，无静默断链 ✅
- 无路由异常/错误事件；response_timing 725ms。
- 备注：confirm_token=null 系复审 B1 设计（token 不再经事件流分发），非缺陷。
- 立项确认动作本身受 BUG-E2E-02 阻断（proposal 不落库），与本条「路由 fallback 显式可见」
  的验收点无关。
