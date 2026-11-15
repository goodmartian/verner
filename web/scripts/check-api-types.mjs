// Fails when src/api/schema.d.ts is not what the current api/openapi.json generates.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import process from 'node:process';

const spec = '../api/openapi.json';
const dir = mkdtempSync(join(tmpdir(), 'senda-api-'));
const fresh = join(dir, 'schema.d.ts');
try {
  execFileSync('pnpm', ['exec', 'openapi-typescript', spec, '-o', fresh], { stdio: 'ignore' });
  if (readFileSync(fresh, 'utf8') !== readFileSync('src/api/schema.d.ts', 'utf8')) {
    process.stderr.write('src/api/schema.d.ts is stale: run `pnpm api:types`\n');
    process.exitCode = 1;
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}
