# Claudian upstream source

- Repository: https://github.com/YishenTu/claudian
- Version: 2.2.4
- Approved commit: `d190786d11cc0b067475dcffbf8c334ee565d208`
- Approved archive tree SHA-256: `abc305a71cdf700b7b7721aae0dd9d9c5bface24d6b5d40f24c993ab869933c8`
- Vendor date: 2026-08-28
- License: MIT; see `licenses/claudian-MIT.txt`

The vendoring script accepts either a Git checkout exactly at the approved commit or the approved no-`.git` source archive. Archive approval requires both package version 2.2.4 and the full 1569-file tree digest above.

## Copied scope

- `src/core/execution`
- `src/core/providers`
- `src/core/tools`
- `src/core/security`
- `src/core/prompt`
- `src/core/skills`
- `src/core/process`
- `src/core/storage/VaultFileAdapter.ts`
- `src/providers/claude/execution`
- `src/providers/claude/history`
- `src/providers/claude/runtime`
- `src/providers/claude/security`
- `src/providers/claude/storage`

Files are copied byte-for-byte beneath `src/claudian/<original-path>`. The Obsidian plugin UI entry point and `src/features` UI tree are intentionally excluded.
