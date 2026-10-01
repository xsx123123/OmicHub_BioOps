import { createHash } from 'node:crypto';
import { tool } from 'ai';
import { z } from 'zod';
import type { FlowAgentConfig } from '../config';
import { appendLedger, hasSuccessfulDryRun } from '../ledger';

export function createPlatformTools(cfg: FlowAgentConfig) {
  const submit_plan = tool({
    description: '将已通过 dry-run 的 Snakemake 计划提交到平台确认门，返回 platform run_id。不会在本机执行 Snakemake。',
    inputSchema: z.object({
      task_id: z.string(),
      flow_id: z.string(),
      release_id: z.string(),
      targets: z.array(z.string()).min(1),
      parameters: z.record(z.unknown()).default({}),
      sample_sheet: z.array(z.record(z.unknown())).default([]),
      comparisons: z.array(z.record(z.unknown())).default([]),
      project_slug: z.string().optional(),
      name: z.string().optional(),
    }),
    execute: async ({ task_id, flow_id, release_id, targets, parameters, sample_sheet, comparisons, project_slug, name }) => {
      if (!hasSuccessfulDryRun(cfg.workflowRoot, task_id, targets)) {
        return { ok: false, refused: true, reason: '提交前必须存在成功的 dry_run 台账记录。' };
      }
      if (!cfg.platformURL || !cfg.platformAPIKey || !(project_slug ?? cfg.projectSlug)) {
        return { ok: false, refused: true, reason: '缺少 FLOWAGENT_PLATFORM_URL、FLOWAGENT_PLATFORM_API_KEY 或 FLOWAGENT_PROJECT_SLUG。' };
      }
      const payload = {
        schema_version: 'cygnusx.snakemake_plan.v1',
        project_slug: project_slug ?? cfg.projectSlug,
        flow_id,
        release_id,
        name: name ?? task_id,
        parameters: { ...parameters, targets },
        sample_sheet,
        comparisons,
        request_key: `flowagent:${task_id}`,
      };
      const body = JSON.stringify(payload);
      const digest = createHash('sha256').update(body).digest('hex');
      const response = await fetch(`${cfg.platformURL.replace(/\/$/, '')}/api/v1/runs/snakemake/plan`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-api-key': cfg.platformAPIKey },
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) return { ok: false, status: response.status, error: data };
      appendLedger(cfg.workflowRoot, {
        ts: new Date().toISOString(), task_id, op: 'submit', target: targets.join(' '),
        object: payload.project_slug, result: 'plan_pending', detail: `run_id=${data.run_id}`,
        platform_run_id: data.run_id, project_slug: payload.project_slug, plan_digest: digest,
      });
      return { ok: true, run_id: data.run_id, status: data.status, plan_digest: digest, next: '等待用户确认后调用 MCP confirm_run_plan。' };
    },
  });
  return { submit_plan };
}
