CREATE TABLE tenants(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE principals(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), name TEXT NOT NULL,
 roles TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, human INTEGER NOT NULL, local_only INTEGER NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE resources(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), kind TEXT NOT NULL,
 resource_key TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL,
 created_by TEXT NOT NULL REFERENCES principals(id), created_at TEXT NOT NULL,
 UNIQUE(tenant_id,kind,resource_key,version));
CREATE TABLE resource_heads(tenant_id TEXT NOT NULL REFERENCES tenants(id), kind TEXT NOT NULL, resource_key TEXT NOT NULL,
 resource_id TEXT NOT NULL REFERENCES resources(id), status TEXT NOT NULL, revision INTEGER NOT NULL,
 approved_by TEXT REFERENCES principals(id), approval_evidence TEXT,
 PRIMARY KEY(tenant_id,kind,resource_key));
CREATE TABLE briefs(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), payload TEXT NOT NULL,
 hash TEXT NOT NULL, approved_by TEXT NOT NULL REFERENCES principals(id), created_at TEXT NOT NULL);
CREATE TABLE assets(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), title TEXT NOT NULL,
 latest_version_id TEXT, current_run_id TEXT, released_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE versions(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), asset_id TEXT NOT NULL REFERENCES assets(id),
 ordinal INTEGER NOT NULL, brief_id TEXT NOT NULL REFERENCES briefs(id), payload TEXT NOT NULL, raw BLOB NOT NULL,
 hash TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES principals(id), created_at TEXT NOT NULL,
 UNIQUE(asset_id,ordinal));
CREATE TABLE runs(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), asset_id TEXT NOT NULL REFERENCES assets(id),
 version_id TEXT NOT NULL REFERENCES versions(id), plan TEXT NOT NULL, plan_hash TEXT NOT NULL,
 config TEXT NOT NULL, config_hash TEXT NOT NULL, state TEXT NOT NULL, head_snapshot_id TEXT,
 created_at TEXT NOT NULL);
CREATE TABLE dependencies(run_id TEXT NOT NULL REFERENCES runs(id), tenant_id TEXT NOT NULL REFERENCES tenants(id),
 kind TEXT NOT NULL, resource_key TEXT NOT NULL, resource_id TEXT NOT NULL REFERENCES resources(id),
 revision INTEGER NOT NULL, PRIMARY KEY(run_id,kind,resource_key));
CREATE INDEX dependencies_lookup ON dependencies(tenant_id,kind,resource_key);
CREATE TABLE jobs(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), run_id TEXT UNIQUE NOT NULL REFERENCES runs(id),
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL,
 lease_token TEXT, lease_until REAL, last_error TEXT, created_at TEXT NOT NULL);
CREATE INDEX jobs_pending ON jobs(state,available_at,lease_until);
CREATE TABLE machine_results(run_id TEXT PRIMARY KEY REFERENCES runs(id), tenant_id TEXT NOT NULL REFERENCES tenants(id),
 payload TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE evidence(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), run_id TEXT NOT NULL REFERENCES runs(id),
 payload TEXT NOT NULL, hash TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES principals(id), created_at TEXT NOT NULL);
CREATE TABLE decisions(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), run_id TEXT NOT NULL REFERENCES runs(id),
 kind TEXT NOT NULL, payload TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES principals(id), created_at TEXT NOT NULL);
CREATE INDEX decisions_run ON decisions(run_id);
CREATE UNIQUE INDEX scope_once ON decisions(run_id) WHERE kind='scope';
CREATE TABLE snapshots(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), run_id TEXT NOT NULL REFERENCES runs(id),
 payload TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE approvals(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), run_id TEXT NOT NULL REFERENCES runs(id),
 version_id TEXT NOT NULL REFERENCES versions(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id), snapshot_hash TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES principals(id), payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE releases(id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id), asset_id TEXT NOT NULL REFERENCES assets(id),
 version_id TEXT NOT NULL REFERENCES versions(id), run_id TEXT NOT NULL REFERENCES runs(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
 approval_id TEXT NOT NULL REFERENCES approvals(id), actor_id TEXT NOT NULL REFERENCES principals(id), created_at TEXT NOT NULL,
 UNIQUE(approval_id));
CREATE TABLE idempotency(tenant_id TEXT NOT NULL REFERENCES tenants(id), actor_id TEXT NOT NULL REFERENCES principals(id),
 operation TEXT NOT NULL, idem_key TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL,
 PRIMARY KEY(tenant_id,actor_id,operation,idem_key));
CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, tenant_id TEXT NOT NULL REFERENCES tenants(id),
 actor_id TEXT NOT NULL, kind TEXT NOT NULL, subject_id TEXT NOT NULL, payload TEXT NOT NULL,
 previous_hash TEXT NOT NULL, hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX events_tenant ON events(tenant_id,seq);
