import assert from 'node:assert/strict';
import test from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
const exec = promisify(execFile);

test('isolated cron registration remerges concurrent edits and removal preserves later edits', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'encodingdb-cron-'));
  try {
    const table = path.join(root, 'table');
    await writeFile(table, '17 11 * * * /existing/backup\n');
    const fake = `#!/usr/bin/env python3\nimport pathlib,sys\np=pathlib.Path(${JSON.stringify(table)}); c=pathlib.Path(${JSON.stringify(path.join(root, 'count'))})\nif sys.argv[1]=='-l':\n n=int(c.read_text())+1 if c.exists() else 1;c.write_text(str(n))\n if n==2:p.write_text(p.read_text()+'# concurrent edit preserved\\n')\n print(p.read_text(),end='')\nelse:p.write_text(sys.stdin.read())\n`;
    await writeFile(path.join(root, 'crontab'), fake, { mode: 0o755 });
    const script = path.resolve(import.meta.dirname, '../../scripts/v7-isolated-cron.py');
    const code = `import importlib.util,pathlib,json\nspec=importlib.util.spec_from_file_location('cron',${JSON.stringify(script)});m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\nmarker='encodingdb-isolated-regression';entry='* * * * * /isolated/job # '+marker\nm.update(marker,entry)\np=pathlib.Path(${JSON.stringify(table)});p.write_text(p.read_text()+'31 12 * * * /later/job\\n')\nm.update(marker,None)\ntext=p.read_text();assert '/existing/backup' in text and '# concurrent edit preserved' in text and '/later/job' in text and marker not in text\nprint(json.dumps({'preserved':True}))\n`;
    const result = await exec('python3', ['-c', code], { env: { ...process.env, PATH: root + path.delimiter + process.env.PATH } });
    assert.equal(JSON.parse(result.stdout).preserved, true);
  } finally { await rm(root, { recursive: true, force: true }); }
});
