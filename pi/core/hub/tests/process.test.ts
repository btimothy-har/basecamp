import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { isDaemonCommandForSocket } from "../process.ts";

const SOCKET = "/tmp/fake-home/.pi/basecamp/swarm/daemon.sock";

describe("isDaemonCommandForSocket", () => {
	it("matches the current `basecamp hub` command", () => {
		assert.equal(isDaemonCommandForSocket(`basecamp hub --uds ${SOCKET} --pidfile /x`, SOCKET), true);
	});

	it("matches the legacy `basecamp swarm daemon` command (reapable across the rename)", () => {
		assert.equal(isDaemonCommandForSocket(`basecamp swarm daemon --uds ${SOCKET}`, SOCKET), true);
	});

	it("matches an absolute-path invocation and the --uds=<socket> form", () => {
		assert.equal(isDaemonCommandForSocket(`/usr/local/bin/basecamp hub --uds=${SOCKET}`, SOCKET), true);
	});

	it("rejects a command targeting a different socket", () => {
		assert.equal(isDaemonCommandForSocket(`basecamp hub --uds /other/daemon.sock`, SOCKET), false);
	});

	it("rejects an unrelated command that merely mentions the socket", () => {
		assert.equal(isDaemonCommandForSocket(`cat ${SOCKET}`, SOCKET), false);
		assert.equal(isDaemonCommandForSocket(`basecamp companion --snapshot ${SOCKET}`, SOCKET), false);
	});
});
