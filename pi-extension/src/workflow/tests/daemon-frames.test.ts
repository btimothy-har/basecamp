import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { decodeFrame, encodeFrame, PROTOCOL_VERSION } from "../agents/daemon/frames.ts";

function fixturesDir(): string {
	const here = path.dirname(fileURLToPath(import.meta.url));
	return path.resolve(here, "../../../../protocol/frames");
}

describe("daemon frame codec", () => {
	it("decodes and re-encodes all protocol frame fixtures", () => {
		const dir = fixturesDir();
		const files = fs.readdirSync(dir).filter((file) => file.endsWith(".json"));
		for (const file of files) {
			const raw = fs.readFileSync(path.join(dir, file), "utf8");
			const parsed = decodeFrame(raw);
			assert.equal(parsed.type, file.replace(/\.json$/, ""));
			assert.equal(parsed.v, PROTOCOL_VERSION);
			assert.deepEqual(JSON.parse(encodeFrame(parsed)), JSON.parse(raw));
		}
	});

	it("rejects unknown frame type", () => {
		assert.throws(() => decodeFrame('{"type":"nope","v":1}'), /Unknown frame type/);
	});

	it("rejects unsupported protocol version", () => {
		assert.throws(() => decodeFrame('{"type":"register","v":99}'), /Protocol version mismatch/);
	});
});
