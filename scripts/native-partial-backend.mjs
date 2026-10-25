/** Root-only partial-receipt cleanup; never retries or rewrites a native run. */
import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {DatabaseSync} from 'node:sqlite';
const fail=c=>{throw Error(c)};
function root(p){for(;;p=path.dirname(p)){const s=fs.lstatSync(p);if(s.uid!==0||(s.mode&0o022)||s.isSymbolicLink())fail('ROOT_REQUIRED');if(p===path.dirname(p))break;}}
let db;
try{
 if(process.getuid()!==0)fail('ROOT_REQUIRED');root(process.argv[2]);if(fs.statSync(process.argv[2]).size>65536)fail('CONFIG_LIMIT');const cfg=JSON.parse(fs.readFileSync(process.argv[2]));
 const input=fs.readFileSync(0);if(input.length>65536)fail('REQUEST_LIMIT');const q=JSON.parse(input);if(!['inspect','cleanup','export'].includes(q.action)||Object.keys(q).some(k=>!['action','task_id','record','environment_removed'].includes(k)))fail('REQUEST_SCOPE');
 if(!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(q.task_id))fail('TASK_SCOPE');
 const j=new DatabaseSync(cfg.journal,{readOnly:true}),t=j.prepare('select * from tasks where id=?').get(q.task_id);
 if(!t||t.owner!==cfg.principal||!['execution_failed','partial_ready','cancelled'].includes(t.state))fail('TASK_SCOPE');
 const spec=JSON.parse(t.spec);if(!cfg.allowed_repos.includes(spec.repo)&&!cfg.historical_tasks.includes(t.id))fail('REPO_SCOPE');
 const a=j.prepare('select * from attempts where task_id=? order by number desc limit 1').get(t.id);
 if(!a||a.state!=='terminal'||!a.run_id||!cfg.allowed_agents.includes(a.profile)||JSON.parse(a.evidence??'{}').environment_removed!==true)fail('SOURCE_SCOPE');
 const {createDb}=await import(cfg.module_root+'/@paperclipai/db/dist/index.js');const {sql}=await import(cfg.module_root+'/drizzle-orm/index.js');
 const {agentService}=await import(cfg.module_root+'/@paperclipai/server/dist/services/agents.js');const {logActivity}=await import(cfg.module_root+'/@paperclipai/server/dist/services/activity-log.js');
 db=createDb(cfg.database_url);
 const runs=await db.execute(sql`select r.id,r.status from heartbeat_runs r join issues i on i.id=${t.issue_id} where r.id=${a.run_id} and r.agent_id=${a.profile} and r.company_id=${cfg.company_id} and i.company_id=${cfg.company_id} and i.project_id=${cfg.project_id} and i.assignee_agent_id=${a.profile} and (r.context_snapshot->>'issueId'=${t.issue_id} or r.context_snapshot->>'taskId'=${t.issue_id})`);
 const r=runs[0],agent=await agentService(db).getById(a.profile);
 if(!r||!['failed','succeeded'].includes(r.status)||agent?.companyId!==cfg.company_id)fail('NATIVE_SCOPE');
 root(cfg.producer_path);const hash=crypto.createHash('sha256').update(fs.readFileSync(cfg.producer_path)).digest('hex');
 const verified=hash===cfg.producer_sha256&&agent.adapterType==='process'&&agent.adapterConfig?.command===cfg.command&&JSON.stringify(agent.adapterConfig?.args)===JSON.stringify(cfg.args);
 if(!verified)fail('PRODUCER_CHANGED');
 if(q.action==='inspect')console.log(JSON.stringify({run_id:r.id,agent_id:a.profile,status:r.status,producer_verified:true}));
 else{
  const saved=j.prepare('select record from partial_receipts where task_id=? and run_id=?').get(t.id,a.run_id);if(!saved)fail('PARTIAL_NOT_SECURED');
  const record=JSON.parse(saved.record);if(record.kind!=='partial'||record.complete!==false||(q.action==='cleanup'&&(q.environment_removed!==true||record.snapshot_digest!==q.record?.snapshot_digest))||record.binding.run_id!==a.run_id||record.binding.task_id!==t.id||record.binding.issue_id!==t.issue_id||record.binding.agent_id!==a.profile)fail('PARTIAL_SCOPE');
  const snap=JSON.parse(j.prepare('select snapshot from partial_receipts where task_id=? and run_id=?').get(t.id,a.run_id).snapshot);
  root(cfg.export_root);const base=path.join(cfg.export_root,t.id,a.run_id);fs.mkdirSync(base,{recursive:true,mode:0o755});root(base);for(const directory of [path.join(cfg.export_root,t.id),base])fs.chmodSync(directory,0o755);
  for(const f of snap.manifest.files){const target=path.resolve(base,f.path);if(!target.startsWith(base+path.sep)||f.path.split('/').some(x=>['','..','.'].includes(x)))fail('EXPORT_SCOPE');const data=Buffer.from(f.content_base64,'base64');if(data.length!==f.size||crypto.createHash('sha256').update(data).digest('hex')!==f.sha256)fail('EXPORT_DIGEST');fs.mkdirSync(path.dirname(target),{recursive:true,mode:0o755});root(path.dirname(target));let directory=path.dirname(target);while(directory!==base){fs.chmodSync(directory,0o755);directory=path.dirname(directory)}if(fs.existsSync(target)){root(target);if(crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex')!==f.sha256)fail('EXPORT_CONFLICT');}else fs.writeFileSync(target,data,{flag:'wx',mode:0o444});fs.chmodSync(target,0o444);}
  if(q.action==='cleanup')await db.transaction(async tx=>{
  await tx.execute(sql`select id from agents where id=${a.profile} for update`);
  const current=await agentService(tx).getById(a.profile);
  const active=await tx.execute(sql`select id from heartbeat_runs where agent_id=${a.profile} and status in ('queued','running')`);
  const last=await tx.execute(sql`select id from heartbeat_runs where agent_id=${a.profile} order by created_at desc limit 1`);
  if(active.length||last[0]?.id!==a.run_id||current.pauseReason||!['idle','error'].includes(current.status))fail('PROFILE_CHANGED');
  root(cfg.effects_root);const name=path.join(cfg.effects_root,a.run_id+'.json');
  if(current.status==='error'){
   // clearError is an idempotent metadata cleanup of this exact terminal source;
   // it starts no model, changes no auth, and never reopens the failed task.
   if(!fs.existsSync(name)){const fd=fs.openSync(name,'wx',0o600);try{fs.writeFileSync(fd,JSON.stringify({run_id:a.run_id,digest:record.snapshot_digest,phase:'prepared'}));fs.fsyncSync(fd)}finally{fs.closeSync(fd)}}
   else{const old=JSON.parse(fs.readFileSync(name));if(old.run_id!==a.run_id||old.digest!==record.snapshot_digest)fail('CLEANUP_CONFLICT');}
   await agentService(tx).clearError(a.profile);
   await logActivity(tx,{companyId:cfg.company_id,actorType:'system',actorId:cfg.policy_id,action:'agent.error_cleared',entityType:'agent',entityId:a.profile,details:{reason:'verified terminal final-response deadline; partial files secured; no retry',sourceRunId:a.run_id,partialDigest:record.snapshot_digest}});
   fs.writeFileSync(name,JSON.stringify({run_id:a.run_id,digest:record.snapshot_digest,phase:'confirmed'}),{mode:0o600});
  }
  });
  console.log(JSON.stringify({profile_ready:q.action==='cleanup',export_ready:true,exported_path:base,run_id:a.run_id,model_retried:false,task_reopened:false}));
 }
 j.close();
}catch(e){process.stderr.write(String(e.message).slice(0,100)+'\n');process.exitCode=1;}finally{if(db)await db.$client.end();}
