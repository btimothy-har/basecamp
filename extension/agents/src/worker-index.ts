/**
 * File-backed worker index with atomic writes and auto-pruning.
 *
 * Stores worker metadata in ~/.basecamp/workers.json.
 * Pruning removes closed entries older than 24 hours on every read.
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { WorkerEntry } from "./types.ts";

const INDEX_PATH = path.join(os.homedir(), ".basecamp", "workers.json");
const PRUNE_AGE_MS = 24 * 60 * 60 * 1000;

function readIndex(): WorkerEntry[] {
  try {
    return JSON.parse(fs.readFileSync(INDEX_PATH, "utf-8"));
  } catch {
    return [];
  }
}

function writeIndex(entries: WorkerEntry[]): void {
  const dir = path.dirname(INDEX_PATH);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = `${INDEX_PATH}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(entries, null, 2));
  fs.renameSync(tmp, INDEX_PATH);
}

function prune(entries: WorkerEntry[]): WorkerEntry[] {
  const cutoff = Date.now() - PRUNE_AGE_MS;
  return entries.filter(
    (e) => e.status === "running" || (e.closedAt && e.closedAt > cutoff),
  );
}

export function addWorker(entry: WorkerEntry): void {
  const entries = prune(readIndex());
  entries.push(entry);
  writeIndex(entries);
}

export function closeWorker(name: string): void {
  const entries = readIndex();
  const entry = entries.find((e) => e.name === name);
  if (entry && entry.status !== "closed") {
    entry.status = "closed";
    entry.closedAt = Date.now();
    writeIndex(entries);
  }
}

export function listWorkers(filter?: {
  status?: string;
}): WorkerEntry[] {
  const entries = prune(readIndex());
  writeIndex(entries); // persist prune
  if (filter?.status) return entries.filter((e) => e.status === filter.status);
  return entries;
}
