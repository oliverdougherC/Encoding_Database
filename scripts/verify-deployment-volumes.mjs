#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { realpathSync, statSync } from 'node:fs';
import { isAbsolute } from 'node:path';
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
    const proposed = config.services?.[service]?.volumes?.filter((item) => item.target === target) ?? [];
    const mount = proposed[0];
    if (proposed.length !== 1 || !mount || !['volume', 'bind'].includes(mount.type)
      || typeof mount.source !== 'string' || !mount.source.trim()) {
      throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} must preserve exactly one existing data mount.`);
    }
    for (const container of existing) {
      const current = container.Mounts?.filter((item) => item.Destination === target) ?? [];
      const actual = current[0];
      if (current.length !== 1 || !actual || actual.Type !== mount.type) {
        throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} must preserve its existing mount type and destination.`);
      }
      if (mount.type === 'volume') {
        const intended = config.volumes?.[mount.source]?.name ?? `${project}_${mount.source}`;
        if (typeof intended !== 'string' || !intended.trim() || !actual.Name || actual.Name !== intended) {
          throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} must preserve its existing named volume. Preserve DATABASE_VOLUME_NAME/ARTIFACT_VOLUME_NAME explicitly.`);
        }
        checked.push({ service, target, volume: intended });
      } else {
        let intended;
        let currentSource;
        try {
          if (typeof actual.Source !== 'string' || !isAbsolute(actual.Source) || !isAbsolute(mount.source)) throw new Error('Absolute data paths required');
          intended = realpathSync(mount.source);
          currentSource = realpathSync(actual.Source);
          if (!statSync(intended).isDirectory() || !statSync(currentSource).isDirectory()) throw new Error('Data directory required');
        } catch {
          throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} requires existing absolute bind data directories.`);
        }
        if (intended !== currentSource) {
          throw new DeploymentVolumeError(`Refusing rollout: ${service} ${target} must preserve its existing canonical bind source.`);
        }
        checked.push({ service, target, type: 'bind', source: intended });
      }
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
