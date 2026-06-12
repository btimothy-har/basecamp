import assert from "node:assert/strict";
import * as path from "node:path";
import { describe, it } from "node:test";
import { resolveDaemonPaths } from "../agents/daemon/paths.ts";

describe("daemon paths", () => {
	it("resolves runtime dir, socket, and lock paths under ~/.pi/agent/basecamp", () => {
		const fakeHome = path.join(path.sep, "tmp", "fake-home");
		const paths = resolveDaemonPaths(fakeHome);
		assert.equal(paths.runtimeDir, path.join(fakeHome, ".pi", "agent", "basecamp"));
		assert.equal(paths.socketPath, path.join(fakeHome, ".pi", "agent", "basecamp", "daemon.sock"));
		assert.equal(paths.spawnLockPath, path.join(fakeHome, ".pi", "agent", "basecamp", "daemon.spawn.lock"));
		assert.equal(paths.pidPath, path.join(fakeHome, ".pi", "agent", "basecamp", "daemon.pid"));
	});
});
