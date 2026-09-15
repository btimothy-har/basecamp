import { readFileSync } from "node:fs";
import * as path from "node:path";
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

const DEFAULT_SOURCE_LINE_LIMIT = 500;
const FILE_LENGTH_REMINDER_TYPE = "basecamp-file-length-reminder";

const SOURCE_SUFFIXES = new Set([
	".bash",
	".c",
	".cc",
	".cjs",
	".cpp",
	".cs",
	".css",
	".cxx",
	".go",
	".h",
	".hh",
	".hpp",
	".htm",
	".html",
	".java",
	".jl",
	".js",
	".jsx",
	".kt",
	".kts",
	".lua",
	".mjs",
	".php",
	".py",
	".pyi",
	".rb",
	".rs",
	".scala",
	".sh",
	".sql",
	".swift",
	".ts",
	".tsx",
	".zsh",
]);

const SOURCE_LINE_LIMITS = new Map<string, number>([
	[".htm", 350],
	[".html", 350],
	[".ts", 350],
	[".tsx", 350],
	[".bash", 400],
	[".sh", 400],
	[".zsh", 400],
	[".sql", 800],
]);

function lineLimit(filePath: string): { limit: number; suffix: string } | null {
	const suffix = path.extname(filePath).toLowerCase();
	if (!SOURCE_SUFFIXES.has(suffix)) return null;
	return { limit: SOURCE_LINE_LIMITS.get(suffix) ?? DEFAULT_SOURCE_LINE_LIMIT, suffix };
}

function lineCount(content: string): number {
	if (content === "") return 0;
	// Counting only newlines matches editor gutters and the repository's hard checker.
	return content.split("\n").length - (content.endsWith("\n") ? 1 : 0);
}

function reminderContent(filePath: string, lines: number, limit: number, suffix: string): string {
	return (
		"<system-reminder>\n" +
		`File-length reminder: ${JSON.stringify(filePath)} is now ${lines} lines, over the ${limit}-line cap for ${suffix} source files. ` +
		"The edit succeeded; this is advisory. Split the file along genuine responsibility seams into focused modules. " +
		"Do not compress formatting or create continuation files merely to satisfy the cap, and follow any tighter project-specific limit.\n" +
		"</system-reminder>"
	);
}

export default function registerFileLengthReminder(omp: ExtensionAPI): void {
	const remindedPaths = new Set<string>();
	const reset = (): void => remindedPaths.clear();

	omp.on("session_start", reset);
	omp.on("agent_end", (event) => {
		if (event.willContinue !== true) reset();
	});

	omp.on("tool_result", (event, ctx) => {
		if (event.isError) return;
		if (event.toolName !== "edit" && event.toolName !== "write") return;

		const rawPath = event.input.path;
		if (typeof rawPath !== "string" || rawPath === "") return;

		try {
			const resolvedPath = path.isAbsolute(rawPath) ? path.resolve(rawPath) : path.resolve(ctx.cwd, rawPath);
			const policy = lineLimit(resolvedPath);
			if (!policy) return;

			const lines = lineCount(readFileSync(resolvedPath, "utf8"));
			if (lines <= policy.limit) {
				remindedPaths.delete(resolvedPath);
				return;
			}
			if (remindedPaths.has(resolvedPath)) return;

			omp.sendMessage(
				{
					customType: FILE_LENGTH_REMINDER_TYPE,
					content: reminderContent(resolvedPath, lines, policy.limit, policy.suffix),
					display: false,
				},
				{ deliverAs: "steer" },
			);
			remindedPaths.add(resolvedPath);
		} catch {
			// Advisory failures must never affect a successful edit.
		}
	});
}
