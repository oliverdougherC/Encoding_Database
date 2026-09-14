#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export class DeploymentVolumeError extends Error {}

/** Refuse a rollout which would silently attach existing services to new data. */
export function verifyDeploymentVolumes(config, containers) {
  const project = config.name;
  if (!project) throw new DeploymentVolumeError('Compose project name is required to verify existing data bindings.');
  const protectedMounts = [['db', '/var/lib/postgresql/data'], ['server', '/app/artifacts']];
  const checked = [];
  for (const [service, target] of protectedMounts) {
    const existing = containers.filter((item) => item.Config?.Labels?.['com.docker.compose.project'] === project && item.Config?.Labels?.['com.docker.compose.service'] === service);
    if (!existing.length) continue;
    const mount = config.services?.[service]?.volumes?.find((item) => item.target === target);
    if (!mount || mount.type !== 'volume') throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} must preserve its existing named volume.`);
    const intended = config.volumes?.[mount.source]?.name ?? `${project}_${mount.source}`;
    for (const container of existing) {
      const actual = container.Mounts?.find((item) => item.Destination === target);
      if (!actual || actual.Type !== 'volume' || actual.Name !== intended) {
        throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} uses ${actual?.Name ?? actual?.Type ?? 'no matching mount'}, but Compose selects ${intended}. Preserve the existing DATABASE_VOLUME_NAME/ARTIFACT_VOLUME_NAME explicitly.`);
      }
      checked.push({ service, target, volume: intended });
    }
  }
  return { project, checked };
}

export function inspectDeploymentVolumes(composeFile) {
  const config = JSON.parse(execFileSync('docker', ['compose', '-f', composeFile, 'config', '--format', 'json'], { encoding: 'utf8' }));
  const ids = execFileSync('docker', ['ps', '-aq', '--filter', `label=com.docker.compose.project=${config.name}`], { encoding: 'utf8' }).trim().split(/\s+/).filter(Boolean);
  const containers = ids.length ? JSON.parse(execFileSync('docker', ['inspect', ...ids], { encoding: 'utf8' })) : [];
  return verifyDeploymentVolumes(config, containers);
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) {
  try { console.log(JSON.stringify({ ok: true, ...inspectDeploymentVolumes(process.argv[2] || 'docker-compose.prod.yml') })); }
  catch (error) {
    // Docker config/inspect can contain credentials: never echo captured output.
    console.error(error instanceof DeploymentVolumeError ? error.message : 'Unable to verify deployment volume bindings; refusing rollout.');
    process.exitCode = 1;
  }
}
