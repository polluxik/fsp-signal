import { defineConfig } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = dirname(fileURLToPath(import.meta.url))
const repositoryRoot = resolve(frontendRoot, '..')
const python = process.env.FSP_SIGNAL_E2E_PYTHON ?? resolve(
  repositoryRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)
if (!existsSync(python)) {
  throw new Error(`Python environment not found: ${python}. Set FSP_SIGNAL_E2E_PYTHON to its interpreter.`)
}
const runId = process.env.FSP_SIGNAL_E2E_RUN_ID ?? randomUUID()
process.env.FSP_SIGNAL_E2E_RUN_ID = runId
const apiPort = 32_768 + Number.parseInt(runId.slice(0, 4), 16) % (49_151 - 32_768)
const frontendPort = 49_152 + Number.parseInt(runId.slice(0, 4), 16) % (65_535 - 49_152)
const databasePath = join(tmpdir(), `fsp-signal-playwright-${runId}.sqlite3`)
const artifactsPath = join(tmpdir(), `fsp-signal-playwright-results-${runId}`)

process.env.FSP_SIGNAL_E2E_DB = databasePath
process.env.FSP_SIGNAL_E2E_ARTIFACTS = artifactsPath

export default defineConfig({
  testDir: './tests',
  testMatch: '**/core-flow.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  reporter: 'list',
  outputDir: artifactsPath,
  globalTeardown: './tests/cleanup-e2e-db.ts',
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    browserName: 'chromium',
    launchOptions: { channel: 'chrome' },
    viewport: { width: 1365, height: 920 },
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" -m alembic upgrade head && "${python}" -m backend.seed_demo && "${python}" -m uvicorn backend.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: repositoryRoot,
      url: `http://127.0.0.1:${apiPort}/api/docs`,
      timeout: 120_000,
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 1_000 },
      env: {
        ...process.env,
        APP_MODE: 'demo',
        DATABASE_URL: `sqlite:///${databasePath}`,
        PUBLIC_BASE_URL: `http://127.0.0.1:${frontendPort}`,
        MATCH_ALGORITHM_VERSION: 'match_v2',
        SESSION_SECURE: 'false',
      },
    },
    {
      command: `npm run dev -- --port ${frontendPort} --strictPort`,
      cwd: frontendRoot,
      url: `http://127.0.0.1:${frontendPort}`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        ...process.env,
        FSP_SIGNAL_API_TARGET: `http://127.0.0.1:${apiPort}`,
      },
    },
  ],
})
