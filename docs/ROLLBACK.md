# Rollback

1. Stop accepting new submissions and disable the MCP client entry.
2. Inspect known task/run IDs. Do not release a worker slot or delete a Job solely
   because a client disconnected. Finish or cancel through native operator tools.
3. Disable the dedicated coordinator's on-demand execution while retaining its
   record, key metadata and audit history.
4. Stop/disable the local broker unit. There is no public listener to remove.
5. Keep the journal and exact package/config version. Before updates, run
   `paperclip-bridge --config PRIVATE_PATH backup --destination NEW_FILE`.
6. A SQLite backup alone does not roll back Paperclip. Reconcile all remote writes
   made after the snapshot before restoring it, or it could duplicate old intents.
7. To roll back code, install the prior reviewed wheel in its virtualenv and use
   the matching schema version. Unknown schema versions fail closed.
8. Revoke the dedicated key when retiring the integration. Revocation does not
   delete its tasks; key-bound origin rules may require an operator for later
   access. Never erase those records to conceal a failed test.

Do not restore global Authentik, proxy, network or Paperclip database backups to
undo this pilot. It does not require changes to those services' code or routing.
