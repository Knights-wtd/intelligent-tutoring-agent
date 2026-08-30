# Claudian downstream patches

The mirrored files listed in `FILES.json` are copied byte-for-byte from Claudian 2.2.4. No patch is applied inside `src/claudian` during vendoring; every listed hash therefore describes the copied upstream bytes.

The runtime integration layer must keep the following downstream adaptations outside the mirrored tree, or record any future edits here before regenerating `FILES.json`:

1. **Import redirection** - host-facing imports are redirected through agent-runtime adapters instead of importing the Obsidian plugin entry point.
2. **Obsidian boundary replacement** - Vault, workspace, notice, and UI dependencies are replaced by explicit host interfaces; no React or Obsidian settings component reads attribution files.
3. **Node host adaptation** - process lifecycle, filesystem paths, environment access, and stream cleanup are supplied by the Node 24 runtime host.
4. **Security patches** - permission updates, path containment, command execution, and persisted session data remain behind the runtime capability and authorization boundaries.

Conformance tests under `tests/conformance` preserve selected upstream behavioral intent while avoiding UI-only dependencies. Adapter-specific differences are asserted there rather than hidden in the mirrored source.
