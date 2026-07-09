import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it } from "node:test";
import { fileURLToPath } from "node:url";
import { decodeFrame, encodeFrame, FRAME_TYPES, PROTOCOL_VERSION } from "../daemon/frames/index.ts";

function fixturesDir(): string {
	const here = path.dirname(fileURLToPath(import.meta.url));
	return path.resolve(here, "../../../protocol/frames");
}

function pythonFramesPath(): string {
	const here = path.dirname(fileURLToPath(import.meta.url));
	return path.resolve(here, "../../../py/basecamp/swarm/frames.py");
}

describe("daemon frame codec", () => {
	it("keeps frame types in parity with protocol fixtures", () => {
		const dir = fixturesDir();
		const fixtureTypes = new Set(
			fs
				.readdirSync(dir)
				.filter((file) => file.endsWith(".json"))
				.map((file) => file.replace(/\.json$/, "")),
		);
		const frameTypes = new Set(FRAME_TYPES);
		assert.deepEqual(frameTypes, fixtureTypes);
	});

	it("keeps protocol version in parity with the Python daemon", () => {
		const source = fs.readFileSync(pythonFramesPath(), "utf8");
		const match = source.match(/^PROTOCOL_VERSION = (\d+)$/m);
		assert.ok(match);
		assert.equal(Number(match[1]), PROTOCOL_VERSION);
	});

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
		assert.throws(() => decodeFrame('{"type":"nope","v":2}'), /Unknown frame type/);
	});

	it("rejects unsupported protocol version", () => {
		assert.throws(() => decodeFrame('{"type":"register","v":99}'), /Protocol version mismatch/);
	});
});
