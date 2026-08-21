# E2E-10 新链路物化 —— 红（被 BUG-E2E-02 阻断）

## 验收口径（任务书 2.2）

> 房间立项 Case 跑交付 → 期望：产物入项目目录、我的文件可见；新旧路径行为一致；证据：文件树截图。

## 阻断原因

- 「房间立项 → Case」链路被 **BUG-E2E-02** 打断：立项卡事件落 Bridge，但 `room.proposal` 永不落库（celery 任务 `_respond_to_room_namespace_message`，`src/omichub/infrastructure/celery_app/tasks/agentteams.py:112-137` 全程无 commit，persist 只 flush），导致 `confirm-proposal` 恒 400「立项确认令牌无效或已使用」（实测响应存 `../E2E-9/confirm_proposal_400.json`），房间永远走不到 Case。
- 详见 `../env/BUG-02-proposal-not-persisted.md`。

## 部分证据（旧路径）

- 旧路径（POST /api/v1/agent-teams/cases 直接建 Case）在 E2E-1 中走通到 preflight（见 `../E2E-1/result.md`）。因输入文件为伪造文件名，worker 执行阶段预期失败，「产物入项目目录」未到达。
- 新旧路径行为一致性无法比对：新路径（房间立项）断在 confirm-proposal。

## 结论

🟥 红（阻断，非目标功能本身失败）。主干 hotfix BUG-E2E-02 后重跑本条。
