import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it, type TestContext } from "node:test";

const shimPath = path.resolve(import.meta.dirname, "../bin/playwright-cli");
const cliEntryPath = path.resolve(import.meta.dirname, "../../../node_modules/@playwright/cli/playwright-cli.js");
const configuredEnv = [
	"BASECAMP_BROWSER_PATH",
	"PLAYWRIGHT_MCP_BROWSER",
	"PLAYWRIGHT_MCP_EXECUTABLE_PATH",
	"PLAYWRIGHT_MCP_HEADLESS",
	"PLAYWRIGHT_MCP_ISOLATED",
	"PLAYWRIGHT_MCP_OUTPUT_DIR",
	"PLAYWRIGHT_MCP_OUTPUT_MAX_SIZE",
];

function tempDir(t: TestContext, prefix: string): string {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
	t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
	return dir;
}

function baseEnv(home: string): NodeJS.ProcessEnv {
	const env: NodeJS.ProcessEnv = {
		...process.env,
		BASECAMP_AGENT_DEPTH: "0",
		HOME: home,
	};
	for (const name of configuredEnv) delete env[name];
	return env;
}

function runShim(args: string[], env: NodeJS.ProcessEnv) {
	return spawnSync(shimPath, args, { encoding: "utf8", env });
}

function escapeRegex(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function createFakeNode(t: TestContext): string {
	const binDir = tempDir(t, "basecamp-browser-fake-bin-");
	const executable = path.join(binDir, "node");
	fs.writeFileSync(
		executable,
		`#!/bin/sh
printf 'HEADLESS=%s\\n' "$PLAYWRIGHT_MCP_HEADLESS"
printf 'ISOLATED=%s\\n' "$PLAYWRIGHT_MCP_ISOLATED"
printf 'BROWSER=%s\\n' "$PLAYWRIGHT_MCP_BROWSER"
printf 'EXECUTABLE=%s\\n' "${"$"}{PLAYWRIGHT_MCP_EXECUTABLE_PATH:-}"
printf 'OUTPUT_DIR=%s\\n' "$PLAYWRIGHT_MCP_OUTPUT_DIR"
printf 'OUTPUT_MAX_SIZE=%s\\n' "$PLAYWRIGHT_MCP_OUTPUT_MAX_SIZE"
printf 'NO_UPDATE_NOTIFIER=%s\\n' "$NO_UPDATE_NOTIFIER"
for argument in "$@"; do printf 'ARG=%s\\n' "$argument"; done
touch "$HOME/umask-probe"
`,
		{ mode: 0o755 },
	);
	return binDir;
}

describe("playwright-cli shim", () => {
	it("refuses subagent and malformed depth before invoking the CLI", (t) => {
		const home = tempDir(t, "basecamp-browser-blocked-home-");
		for (const depth of ["1", "2", "invalid", "-1"]) {
			const result = runShim(["--version"], { ...baseEnv(home), BASECAMP_AGENT_DEPTH: depth });
			assert.notEqual(result.status, 0, `depth ${depth} should be rejected`);
			assert.match(result.stderr, /BASECAMP_AGENT_DEPTH|primary Basecamp sessions/);
		}
		assert.equal(fs.existsSync(path.join(home, ".pi")), false);
	});

	it("invokes the exact pinned package and creates a private default output directory", (t) => {
		const home = tempDir(t, "basecamp-browser-version-home-");
		const result = runShim(["--version"], baseEnv(home));
		const outputDir = path.join(home, ".pi", "basecamp", "browser", "playwright-output");

		assert.equal(result.status, 0, result.stderr);
		assert.equal(result.stdout.trim(), "0.1.17");
		assert.equal(fs.statSync(outputDir).mode & 0o777, 0o700);
	});

	it("passes private headed persistent defaults and the Basecamp browser override", (t) => {
		const home = tempDir(t, "basecamp-browser-defaults-home-");
		const fakeNodeDir = createFakeNode(t);
		const fakeBrowser = path.join(home, "browser");
		fs.writeFileSync(fakeBrowser, "", { mode: 0o700 });
		const env = baseEnv(home);
		env.PATH = [fakeNodeDir, process.env.PATH ?? ""].join(path.delimiter);
		env.BASECAMP_BROWSER_PATH = fakeBrowser;

		const result = runShim(["--version"], env);
		const outputDir = path.join(home, ".pi", "basecamp", "browser", "playwright-output");

		assert.equal(result.status, 0, result.stderr);
		assert.match(result.stdout, /^HEADLESS=false$/m);
		assert.match(result.stdout, /^ISOLATED=false$/m);
		assert.match(result.stdout, /^BROWSER=chrome$/m);
		assert.match(result.stdout, new RegExp(`^EXECUTABLE=${escapeRegex(fakeBrowser)}$`, "m"));
		assert.match(result.stdout, new RegExp(`^OUTPUT_DIR=${escapeRegex(outputDir)}$`, "m"));
		assert.match(result.stdout, /^OUTPUT_MAX_SIZE=536870912$/m);
		assert.match(result.stdout, /^NO_UPDATE_NOTIFIER=1$/m);
		assert.match(result.stdout, new RegExp(`^ARG=${escapeRegex(cliEntryPath)}$`, "m"));
		assert.match(result.stdout, /^ARG=--version$/m);
		assert.equal(fs.statSync(outputDir).mode & 0o777, 0o700);
		assert.equal(fs.statSync(path.join(home, "umask-probe")).mode & 0o777, 0o600);
	});

	it("preserves explicit Playwright overrides", (t) => {
		const home = tempDir(t, "basecamp-browser-overrides-home-");
		const fakeNodeDir = createFakeNode(t);
		const customOutput = path.join(home, "custom-output");
		const env = {
			...baseEnv(home),
			BASECAMP_BROWSER_PATH: "/missing/basecamp-browser",
			PATH: [fakeNodeDir, process.env.PATH ?? ""].join(path.delimiter),
			PLAYWRIGHT_MCP_BROWSER: "webkit",
			PLAYWRIGHT_MCP_EXECUTABLE_PATH: "/custom/browser",
			PLAYWRIGHT_MCP_HEADLESS: "true",
			PLAYWRIGHT_MCP_ISOLATED: "true",
			PLAYWRIGHT_MCP_OUTPUT_DIR: customOutput,
			PLAYWRIGHT_MCP_OUTPUT_MAX_SIZE: "12345",
		};

		const result = runShim(["--version"], env);

		assert.equal(result.status, 0, result.stderr);
		assert.match(result.stdout, /^HEADLESS=true$/m);
		assert.match(result.stdout, /^ISOLATED=true$/m);
		assert.match(result.stdout, /^BROWSER=webkit$/m);
		assert.match(result.stdout, /^EXECUTABLE=\/custom\/browser$/m);
		assert.match(result.stdout, new RegExp(`^OUTPUT_DIR=${escapeRegex(customOutput)}$`, "m"));
		assert.match(result.stdout, /^OUTPUT_MAX_SIZE=12345$/m);
		assert.equal(fs.existsSync(path.join(home, ".pi")), false);
	});

	it("blocks commands that would install or download browsers", (t) => {
		const home = tempDir(t, "basecamp-browser-install-home-");
		const blockedCommands = [
			["install"],
			["-s=test", "install"],
			["--session", "test", "install-browser"],
			["--session=test", "install-browser"],
		];
		for (const args of blockedCommands) {
			const result = runShim(args, baseEnv(home));
			assert.notEqual(result.status, 0);
			assert.match(result.stderr, /installation is managed by Basecamp/);
		}
	});
});
