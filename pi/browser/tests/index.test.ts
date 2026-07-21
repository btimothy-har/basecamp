import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { loadSkillsFromDir } from "@earendil-works/pi-coding-agent";
import registerBrowser, { browserCliBinDir, browserCliPath, browserSkillPath } from "../index.ts";

interface ResourceContribution {
	skillPaths: string[];
}

type ResourceHandler = () => ResourceContribution;

function createMockPi(): { pi: ExtensionAPI; resourceHandlers: ResourceHandler[] } {
	const resourceHandlers: ResourceHandler[] = [];
	const pi = {
		on(event: string, handler: ResourceHandler) {
			if (event === "resources_discover") resourceHandlers.push(handler);
		},
	};
	return { pi: pi as unknown as ExtensionAPI, resourceHandlers };
}

function preserveSessionEnv(t: TestContext): void {
	const originalDepth = process.env.BASECAMP_AGENT_DEPTH;
	const originalPath = process.env.PATH;
	t.after(() => {
		if (originalDepth === undefined) delete process.env.BASECAMP_AGENT_DEPTH;
		else process.env.BASECAMP_AGENT_DEPTH = originalDepth;
		if (originalPath === undefined) delete process.env.PATH;
		else process.env.PATH = originalPath;
	});
}

describe("browser CLI PATH", () => {
	it("prepends one shim entry and preserves unrelated PATH entries", () => {
		const current = ["/first", "", browserCliBinDir, "/second", browserCliBinDir].join(path.delimiter);
		const configured = browserCliPath(current, true);

		assert.deepEqual(configured?.split(path.delimiter), [browserCliBinDir, "/first", "", "/second"]);
	});

	it("removes every shim entry and handles an initially undefined PATH", () => {
		const current = [browserCliBinDir, "/first", browserCliBinDir, "/second"].join(path.delimiter);

		assert.deepEqual(browserCliPath(current, false)?.split(path.delimiter), ["/first", "/second"]);
		assert.equal(browserCliPath(undefined, false), undefined);
		assert.equal(browserCliPath(undefined, true), browserCliBinDir);
	});
});

describe("browser resource discovery", () => {
	it("exposes the skill to primary sessions and stays idempotent across registration", (t) => {
		preserveSessionEnv(t);
		process.env.BASECAMP_AGENT_DEPTH = "0";
		process.env.PATH = ["/first", browserCliBinDir, "/second", browserCliBinDir].join(path.delimiter);

		const first = createMockPi();
		registerBrowser(first.pi);
		const second = createMockPi();
		registerBrowser(second.pi);

		assert.deepEqual(process.env.PATH?.split(path.delimiter), [browserCliBinDir, "/first", "/second"]);
		assert.equal(first.resourceHandlers.length, 1);
		assert.deepEqual(first.resourceHandlers[0]?.(), { skillPaths: [browserSkillPath] });
		assert.equal(second.resourceHandlers.length, 1);
	});

	it("removes the shim and hides the skill in subagent sessions", (t) => {
		preserveSessionEnv(t);
		process.env.BASECAMP_AGENT_DEPTH = "1";
		process.env.PATH = ["/first", browserCliBinDir, "/second"].join(path.delimiter);
		const { pi, resourceHandlers } = createMockPi();

		registerBrowser(pi);

		assert.deepEqual(process.env.PATH?.split(path.delimiter), ["/first", "/second"]);
		assert.equal(resourceHandlers.length, 0);
	});
});

describe("playwright-cli skill", () => {
	it("loads cleanly and contains the Basecamp-specific workflow and policy", () => {
		const result = loadSkillsFromDir({ dir: path.dirname(browserSkillPath), source: "browser-test" });
		const content = fs.readFileSync(browserSkillPath, "utf8");

		assert.deepEqual(result.diagnostics, []);
		assert.equal(result.skills.length, 1);
		assert.equal(result.skills[0]?.name, "playwright-cli");
		assert.match(result.skills[0]?.description ?? "", /browser/i);
		for (const guidance of [
			"snapshot",
			"run-code",
			"read",
			"--help",
			"persistent",
			"playwright-cli route",
			"playwright-cli unroute",
			"playwright-cli reload",
			"playwright-cli resize",
			"playwright-cli console",
			"playwright-cli requests",
			"playwright-cli show --annotate",
		]) {
			assert.ok(content.includes(guidance), `skill should explain ${guidance}`);
		}
		assert.match(content, /Never use `npx`/);
		assert.match(content, /relative `--filename` writes into the current directory/);
		assert.match(content, /direct `file:` navigation is blocked/);
		assert.ok(content.includes("distinct reserved `.test` hostname"));
		assert.ok(content.includes("http://prototype.test/"));
		assert.ok(content.includes('--content-type="text/html; charset=utf-8"'));
		assert.ok(content.includes('--body="$(cat'));
		assert.equal(content.includes("screenshot --filename"), false);
		assert.equal(content.includes("npm install"), false);
	});
});
