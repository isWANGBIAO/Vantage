"use strict";

const fs = require("node:fs/promises");
const { createReadStream } = require("node:fs");
const path = require("node:path");
const net = require("node:net");
const { createHash, randomUUID } = require("node:crypto");
const MIGRATION_MARKER = '.vantage-never-stop-migration.json';

async function lstatIfPresent(file) {
  try {
    return await fs.lstat(file);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

function ordinaryEntry(stat, file) {
  if (stat.isSymbolicLink()) throw Error(`symbolic link cannot be migrated: ${file}`);
  if (!stat.isDirectory() && !stat.isFile())
    throw Error(`Unsupported data entry cannot be migrated: ${file}`);
}

async function fingerprint(file) {
  const hash = createHash("sha256");
  let size = 0;
  for await (const chunk of createReadStream(file)) {
    hash.update(chunk);
    size += chunk.length;
  }
  return `${size}:${hash.digest("hex")}`;
}

async function manifest(root) {
  const entries = [];
  async function visit(dir, relative) {
    for (const name of (await fs.readdir(dir)).sort()) {
      if (!relative && name === "runner.lock") continue;
      const child = path.join(dir, name);
      const childRelative = path.join(relative, name);
      const stat = await fs.lstat(child);
      ordinaryEntry(stat, child);
      if (stat.isDirectory()) {
        entries.push({ relative: childRelative, type: "directory" });
        await visit(child, childRelative);
      } else {
        entries.push({ relative: childRelative, type: "file", fingerprint: await fingerprint(child) });
      }
    }
  }
  await visit(root, "");
  return entries;
}

function assertSameManifest(expected, actual) {
  if (JSON.stringify(expected) !== JSON.stringify(actual))
    throw Error("Legacy data changed or copied bytes differ during migration");
}

async function acquireLegacyLock(legacyDir, platform) {
  if (platform === "win32") {
    // The old Runner hashes this exact canonical string to name its pipe.
    const canonical = (await fs.realpath(legacyDir)).toLowerCase();
    const key = createHash("sha256").update(canonical).digest("hex");
    const server = net.createServer((socket) => socket.end());
    await new Promise((resolve, reject) => {
      const onError = (error) => {
        server.off("listening", onListening);
        reject(Error(error.code === "EADDRINUSE"
          ? "A runner is already active for this data directory"
          : error.message));
      };
      const onListening = () => {
        server.off("error", onError);
        resolve();
      };
      server.once("error", onError);
      server.once("listening", onListening);
      server.listen(`\\\\.\\pipe\\vantage-never-stop-${key}`);
    });
    let released;
    return () => {
      if (!released) released = new Promise((resolve, reject) =>
        server.close((error) => error ? reject(error) : resolve()));
      return released;
    };
  }

  // The old Unix Runner uses this directory. Treat an existing lock as live:
  // recovering a stale PID here could race another process during migration.
  const lockDir = path.join(legacyDir, "runner.lock");
  try {
    await fs.mkdir(lockDir);
  } catch (error) {
    if (error.code === "EEXIST")
      throw Error("A runner lock already exists for this data directory");
    throw error;
  }
  try {
    await fs.writeFile(path.join(lockDir, "pid"), String(process.pid));
  } catch (error) {
    await fs.rm(lockDir, { recursive: true, force: true });
    throw error;
  }
  let released;
  return () => {
    if (!released) released = fs.rm(lockDir, { recursive: true, force: true });
    return released;
  };
}

async function prepareNeverStopData({ targetDir, legacyDir, platform = process.platform }) {
  if (!targetDir || !legacyDir) throw TypeError("targetDir and legacyDir are required");
  const source = path.resolve(legacyDir);
  const target = path.resolve(targetDir);
  const withinSource = path.relative(source, target);
  if (!withinSource || (!withinSource.startsWith("..") && !path.isAbsolute(withinSource)))
    throw Error("Target data directory must be outside the legacy directory");

  const sourceStat = await lstatIfPresent(source);
  if (!sourceStat) return { migrated: false, legacyResolved: false, releaseLegacyLock: async () => {} };
  ordinaryEntry(sourceStat, source);
  if (!sourceStat.isDirectory()) throw Error("Legacy data path must be a directory");

  const releaseLegacyLock = await acquireLegacyLock(source, platform);
  let temporary;
  try {
    const canonical = await fs.realpath(source);
    const sourceId = createHash('sha256')
      .update(platform === 'win32' ? canonical.toLowerCase() : canonical)
      .digest('hex');
    const targetStat = await lstatIfPresent(target);
    if (targetStat) {
      ordinaryEntry(targetStat, target);
      const marker = await fs.readFile(path.join(target, MIGRATION_MARKER), 'utf8').catch(error => {
        if (error.code === 'ENOENT') return null;
        throw error;
      });
      let record;
      try { record = JSON.parse(marker); } catch { record = null; }
      if (record?.schemaVersion !== 1 || record?.sourceId !== sourceId)
        throw Error('Vantage 已有 Never Stop 目标数据，但旧版数据尚未迁入；为避免覆盖或停跑，请先核对并处理两份数据');
      return { migrated: false, legacyResolved: true, releaseLegacyLock };
    }

    const sourceManifest = await manifest(source);
    await fs.mkdir(path.dirname(target), { recursive: true });
    temporary = `${target}.migration-${randomUUID()}`;
    await fs.mkdir(temporary);
    for (const entry of sourceManifest) {
      const destination = path.join(temporary, entry.relative);
      if (entry.type === "directory") await fs.mkdir(destination);
      else {
        await fs.copyFile(path.join(source, entry.relative), destination);
        if (await fingerprint(destination) !== entry.fingerprint)
          throw Error(`Copied bytes differ: ${entry.relative}`);
      }
    }
    assertSameManifest(sourceManifest, await manifest(source));
    assertSameManifest(sourceManifest, await manifest(temporary));
    await fs.writeFile(path.join(temporary, MIGRATION_MARKER), JSON.stringify({ schemaVersion: 1, sourceId }));
    if (await lstatIfPresent(target)) throw Error("Target data directory appeared during migration");
    await fs.rename(temporary, target);
    temporary = undefined;
    return { migrated: true, legacyResolved: true, releaseLegacyLock };
  } catch (error) {
    try {
      if (temporary) await fs.rm(temporary, { recursive: true, force: true });
    } finally {
      await releaseLegacyLock();
    }
    throw error;
  }
}

module.exports = { prepareNeverStopData };
