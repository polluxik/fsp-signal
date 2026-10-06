import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'

export default async function cleanupE2eArtifacts() {
  const database = process.env.FSP_SIGNAL_E2E_DB
  if (database && basename(database).startsWith('fsp-signal-playwright-') && join(tmpdir(), basename(database)) === database) {
    rmSync(database, { force: true })
  }
}
