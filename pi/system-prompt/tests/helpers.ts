import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { TestContext } from "node:test";
import { resetAgentMode, setAgentMode } from "#core/agent-mode/index.ts";

export async function useTempHome(t: TestContext): Promise<string> {
	const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "basecamp-prompts-"));
	const previousHome = process.env.HOME;
	process.env.HOME = homeDir;
	t.after(async () => {
		if (previousHome === undefined) {
			delete process.env.HOME;
		} else {
			process.env.HOME = previousHome;
		}
		await fs.rm(homeDir, { recursive: true, force: true });
	});
	return homeDir;
}

export function useDefaultAgentMode(t: TestContext): void {
	resetAgentMode();
	t.after(() => {
		resetAgentMode();
	});
}

export function useAgentMode(t: TestContext, mode: Parameters<typeof setAgentMode>[0]): void {
	useDefaultAgentMode(t);
	setAgentMode(mode);
}
