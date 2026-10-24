/** Fixed, root-only native capability. Not an HTTP server or model tool. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const fail = code => { throw new Error(code); };
const uuid = x => typeof x === 'string' && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(x);
function rootFile(name) {
  if (!path.isAbsolute(name)) fail('ROOT_PATH_REQUIRED');
  for (let p = name;; p = path.dirname(p)) {
    const st = fs.lstatSync(p);
    if (st.uid !== 0 || (st.mode & 0o022) || st.isSymbolicLink()) fail('ROOT_CONFIG_REQUIRED');
    if (p === path.dirname(p)) break;
  }
}
function durable(name, value, exclusive = false) {
  const fd = fs.openSync(name, exclusive ? 'wx' : 'w', 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(value)); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
  const parent = fs.openSync(path.dirname(name), 'r');
  try { fs.fsyncSync(parent); } finally { fs.closeSync(parent); }
}
let db, lease, board;
try {
  if (process.getuid() !== 0) fail('ROOT_REQUIRED');
  const configPath = process.argv[2]; rootFile(configPath);
  if (fs.statSync(configPath).size > 65536) fail('CONFIG_LIMIT');
  const cfg = JSON.parse(fs.readFileSync(configPath));
  const raw = fs.readFileSync(0); if (raw.length > 65536) fail('REQUEST_LIMIT');
  const q = JSON.parse(raw), policy = cfg.policy;
  if (!['inspect', 'resolve', 'coordinator'].includes(q.action) || policy.enabled !== true) fail('ACTION_DISABLED');
  const load = x => import(pathToFileURL(path.join(cfg.module_root, x)).href);
  const { createDb } = await load('@paperclipai/db/dist/index.js');
  const { sql } = await load('drizzle-orm/index.js');
  const { boardAuthService } = await load('@paperclipai/server/dist/services/board-auth.js');
  const { agentService } = await load('@paperclipai/server/dist/services/agents.js');
  const { logActivity } = await load('@paperclipai/server/dist/services/activity-log.js');
  db = createDb(cfg.database_url); board = boardAuthService(db);
  if (q.action === 'coordinator') {
    const a = await agentService(db).getById(cfg.coordinator_id);
    if (a?.companyId !== policy.company_id || a.adapterType !== 'process') fail('COORDINATOR_SCOPE');
    console.log(JSON.stringify({ id: a.id, company_id: a.companyId, project_id: policy.project_id,
      adapter_type: a.adapterType, observed_at: Date.now() / 1000 }));
  } else {
    if (!uuid(q.task_id) || Object.keys(q).some(k => !['action', 'task_id', 'intent_id', 'worker'].includes(k))) fail('REQUEST_SCOPE');
    const journal = new DatabaseSync(cfg.journal, { readOnly: true });
    const t = journal.prepare('SELECT * FROM tasks WHERE id=?').get(q.task_id);
    if (!t || t.owner !== cfg.principal || !['execution_failed', 'recovery_pending'].includes(t.state)) fail('JOURNAL_SCOPE');
    const spec = JSON.parse(t.spec);
    if (!policy.allowed_repos.includes(spec.repo)) fail('REPO_NOT_APPROVED');
    const intents = journal.prepare('SELECT data FROM recovery_intents WHERE task_id=?').all(t.id).map(x => JSON.parse(x.data));
    const pending = intents.filter(i => i.phase !== 'bound');
    if (pending.length > 1) fail('AMBIGUOUS_INTENT');
    const intent = pending[0];
    const a = intent ? journal.prepare('SELECT * FROM attempts WHERE id=?').get(intent.source_attempt_id)
      : journal.prepare('SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1').get(t.id);
    if (!a || a.state !== 'terminal' || !uuid(a.run_id) || !policy.allowed_agents.includes(a.profile)
        || (spec.profile && spec.profile !== a.profile)) fail('SOURCE_BINDING');
    if (JSON.parse(a.evidence ?? '{}').environment_removed !== true) fail('CLEANUP_UNPROVEN');
    if (q.action === 'resolve' && (!intent || q.intent_id !== intent.id || intent.phase !== 'requesting'
        || intent.policy_id !== policy.policy_id || intent.max_retries !== policy.max_retries
        || intents.length > policy.max_retries || intent.agent_id !== a.profile
        || intent.source_run_id !== a.run_id || intent.issue_id !== t.issue_id
        || intent.reserved_version !== t.version)) fail('INTENT_SCOPE');
    journal.close();
    lease = await board.createNamedBoardApiKey({ userId: cfg.owner_user_id,
      name: 'concord-bounded-recovery-policy', expiresAt: new Date(Date.now() + 90000) });
    async function api(method, suffix, body) {
      const response = await fetch(cfg.base_url + suffix, { method, redirect: 'manual',
        signal: AbortSignal.timeout(15000), headers: { Authorization: 'Bearer ' + lease.token,
          'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      if (!response.ok) fail('NATIVE_HTTP_' + response.status);
      const reader = response.body.getReader(); let total = 0, chunks = [];
      for (;;) { const part = await reader.read(); if (part.done) break;
        total += part.value.length; if (total > 2000000) { await reader.cancel(); fail('RESPONSE_LIMIT'); }
        chunks.push(Buffer.from(part.value)); }
      return total ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : null;
    }
    const issue = await api('GET', '/issues/' + t.issue_id);
    const agent = await agentService(db).getById(a.profile);
    if (issue.companyId !== policy.company_id || issue.projectId !== policy.project_id
        || issue.assigneeAgentId !== a.profile || agent?.companyId !== policy.company_id) fail('NATIVE_SCOPE');
    const runs = await db.execute(sql`SELECT id,company_id,agent_id,status,exit_code,result_json,context_snapshot,created_at
      FROM heartbeat_runs WHERE company_id=${policy.company_id} AND agent_id=${a.profile}
      AND (context_snapshot->>'issueId'=${t.issue_id} OR context_snapshot->>'taskId'=${t.issue_id})`);
    const source = runs.find(r => r.id === a.run_id);
    if (!source || source.company_id !== policy.company_id || source.agent_id !== a.profile) fail('SOURCE_UNAVAILABLE');
    let actionId = intent?.recovery_action_id ?? null;
    const blocker = issue.executionBlocker;
    if (!actionId && blocker?.runId === a.run_id && blocker.agentId === a.profile) actionId = blocker.recoveryActionId;
    if (actionId && !uuid(actionId)) fail('ACTION_BINDING');
    const successors = actionId ? runs.filter(r => r.id !== a.run_id && r.context_snapshot?.recoveryActionId === actionId)
      .map(r => ({ id: r.id, companyId: r.company_id, agentId: r.agent_id,
        status: r.status, contextSnapshot: { issueId: r.context_snapshot.issueId ?? r.context_snapshot.taskId,
          recoveryActionId: r.context_snapshot.recoveryActionId } })) : [];
    const active = await db.execute(sql`SELECT id FROM heartbeat_runs WHERE agent_id=${a.profile}
      AND status IN ('queued','running')`);
    rootFile(cfg.producer_path);
    const actualHash = crypto.createHash('sha256').update(fs.readFileSync(cfg.producer_path)).digest('hex');
    const native = { issue: { id: issue.id, companyId: issue.companyId, projectId: issue.projectId,
      assigneeAgentId: issue.assigneeAgentId, status: issue.status, executionRunId: issue.executionRunId,
      checkoutRunId: issue.checkoutRunId }, agent: { id: agent.id, status: agent.status,
      pauseReason: agent.pauseReason, adapterType: agent.adapterType, command: agent.adapterConfig?.command },
      run: { id: source.id, companyId: source.company_id, agentId: source.agent_id, status: source.status,
        exitCode: source.exit_code, resultJson: { stdout: source.result_json?.stdout ?? '' } },
      recovery_action_id: actionId, successors, other_active_runs: active };
    const producer = { expected_command: cfg.adapter_command, expected_sha256: cfg.producer_sha256,
      actual_sha256: actualHash, exit_code: 75 };
    if (q.action === 'inspect') console.log(JSON.stringify({ native, producer }));
    else {
      // Independent second gate at the privilege boundary, not just policy output.
      if (source.status !== 'failed' || source.exit_code !== 75 || !q.worker
          || q.worker.environment_removed !== true || q.worker.workspace_absent !== true
          || actualHash !== cfg.producer_sha256 || agent.adapterType !== 'process'
          || agent.adapterConfig?.command !== cfg.adapter_command
          || JSON.stringify(agent.adapterConfig?.args) !== JSON.stringify(cfg.adapter_args) || active.length
          || issue.executionRunId || issue.checkoutRunId || !['blocked','todo'].includes(issue.status)
          || ['paused','terminated'].includes(agent.status) || agent.pauseReason
          || agent.orgChainHealth?.status === 'invalid_org_chain' || successors.length
          || blocker?.recoveryActionId !== actionId || blocker.runId !== source.id) fail('RESOLVE_SCOPE');
      const text = source.result_json?.stdout ?? '';
      if (Buffer.byteLength(text) > 4096) fail('ATTESTATION_LIMIT');
      const proof = JSON.parse(text);
      const exact = { kind: 'concord.pre_provider_failure.v1', task_id: t.id, issue_id: t.issue_id,
        agent_id: a.profile, company_id: policy.company_id, project_id: policy.project_id,
        run_id: source.id, producer_sha256: cfg.producer_sha256, error_kind: 'pre_provider_transient' };
      if (Object.keys(proof).length !== Object.keys(exact).length
          || Object.entries(exact).some(([k,v]) => proof[k] !== v)
          || text.trim() !== JSON.stringify(Object.fromEntries(Object.entries(exact).sort(([a],[b])=>a.localeCompare(b))))) fail('ATTESTATION_SCOPE');
      rootFile(cfg.effects_root); const effect = path.join(cfg.effects_root, intent.id + '.json');
      if (fs.existsSync(effect)) fail('WRITE_REQUIRES_RECONCILIATION');
      durable(effect, { intent_id: intent.id, task_id: t.id, run_id: source.id,
        action_id: actionId, policy_id: policy.policy_id, phase: 'requesting', at: Date.now()/1000 }, true);
      if (agent.status === 'error') {
        const latest = [...runs].sort((x,y) => new Date(y.created_at) - new Date(x.created_at))[0];
        const allLatest = await db.execute(sql`SELECT id FROM heartbeat_runs WHERE agent_id=${a.profile}
          ORDER BY created_at DESC LIMIT 1`);
        if (latest.id !== source.id || allLatest[0]?.id !== source.id) fail('PROFILE_HISTORY_CHANGED');
        await agentService(db).clearError(a.profile);
        await logActivity(db, { companyId: policy.company_id, actorType: 'system',
          actorId: policy.policy_id, action: 'agent.error_cleared', entityType: 'agent', entityId: a.profile,
          details: { sourceRunId: source.id, recoveryIntentId: intent.id, reason: 'verified pre-provider failure only' } });
      }
      const result = await api('POST', '/issues/' + t.issue_id + '/recovery-actions/resolve', {
        actionId, outcome: 'restored', sourceIssueStatus: 'todo',
        resolutionNote: 'Root preauthorized bounded recovery ' + policy.policy_id + ', intent ' + intent.id,
        executionReconciliation: { runId: source.id, providerStopped: true, actionOutcome: 'not_performed',
          outcomeEvidence: 'Authenticated fixed-adapter pre-provider exit75, exact source/scope/hash, no worker workspace or Job/pod. Intent ' + intent.id,
          workspaceRepairEvidence: 'Root-owned adapter verified; no provider call occurred. Same task and profile retained; claims and failed source attempt preserved.' } });
      durable(effect, { intent_id: intent.id, task_id: t.id, run_id: source.id,
        action_id: actionId, phase: 'confirmed', at: Date.now()/1000 });
      if (cfg.drop_response_for_repo === spec.repo) {
        const once = path.join(cfg.effects_root, intent.id + '.drop');
        if (!fs.existsSync(once)) { durable(once, { simulated_response_loss: true }, true); fail('SIMULATED_RESPONSE_LOSS'); }
      }
      console.log(JSON.stringify({ action_id: actionId, source_status: result.issue?.status, accepted: true }));
    }
  }
} catch (error) { process.stderr.write(String(error.message).slice(0,100) + '\n'); process.exitCode = 1; }
finally { if (lease && board) await board.revokeBoardApiKey(lease.id); if (db) await db.$client.end(); }
