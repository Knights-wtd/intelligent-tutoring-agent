import { loadRuntimeConfig } from "./config";
import { createRuntimeApplication } from "./bootstrap";

const APPROVED_UPSTREAM_COMMIT = "d190786d11cc0b067475dcffbf8c334ee565d208";

async function main(): Promise<void> {
  const config = loadRuntimeConfig();
  const application = await createRuntimeApplication(config, {
    upstreamCommit: process.env.AGENT_RUNTIME_UPSTREAM_COMMIT ?? APPROVED_UPSTREAM_COMMIT,
  });
  application.server.listen(config.port, config.host, () => {
    process.stdout.write(`Agent Runtime listening on http://${config.host}:${config.port}\n`);
  });
  const shutdown = () => application.server.close(error => {
    if (error) {
      console.error(error);
      process.exitCode = 1;
    }
  });
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
}

void main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
