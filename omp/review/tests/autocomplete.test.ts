import { describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	type AutocompleteItem,
	type AutocompleteProvider,
	CombinedAutocompleteProvider,
	type SlashCommand,
} from "@oh-my-pi/pi-tui";
import createReviewAutocompleteProvider from "../autocomplete.ts";

const BASECAMP_DESCRIPTION = "Test-owned Basecamp review";

function createNativeProvider(directory: string): AutocompleteProvider {
	const commands: Array<AutocompleteItem | SlashCommand> = [
		{
			value: "review",
			label: "review",
			description: BASECAMP_DESCRIPTION,
			icon: "B",
		},
		{
			name: "review",
			description: "Original bundled review workflow (custom command from OMP)",
			icon: "O",
		},
		{
			value: "green",
			label: "green",
			description: "Run green checks",
			icon: "G",
		},
		{
			value: "review-notes",
			label: "review-notes",
			description: "Open review notes",
			icon: "N",
		},
		{
			value: "skill:review",
			label: "skill:review",
			description: "Review skill",
			icon: "S",
		},
		{
			name: "choose",
			description: "Choose a target",
			getArgumentCompletions: () => [
				{ value: "review", label: "review", description: "Argument named review", icon: "A" },
			],
		},
	];
	return new CombinedAutocompleteProvider(commands, directory);
}

function reviewChoices(result: { items: AutocompleteItem[] } | null): AutocompleteItem[] {
	return result?.items.filter((item) => item.value === "review") ?? [];
}

function temporaryDirectory(): string {
	return mkdtempSync(join(tmpdir(), "basecamp-review-autocomplete-"));
}

describe("review autocomplete takeover", () => {
	test("keeps one Basecamp review choice in async and sync command completion", async () => {
		const directory = temporaryDirectory();
		try {
			const provider = createReviewAutocompleteProvider(createNativeProvider(directory), BASECAMP_DESCRIPTION);
			const asyncResult = await provider.getSuggestions(["", "  /rev"], 1, 6);
			const syncResult = provider.trySyncSlashCompletion?.("  /rev") ?? null;

			expect(asyncResult?.prefix).toBe("  /rev");
			expect(syncResult?.prefix).toBe("  /rev");
			expect(reviewChoices(asyncResult)).toEqual([
				{ value: "review", label: "review", description: BASECAMP_DESCRIPTION, icon: "B" },
			]);
			expect(reviewChoices(syncResult)).toEqual(reviewChoices(asyncResult));

			const review = reviewChoices(syncResult)[0];
			if (!review || !syncResult) throw new Error("Basecamp review completion missing");
			expect(provider.applyCompletion(["  /rev"], 0, 6, review, syncResult.prefix)).toMatchObject({
				lines: ["  /review "],
				cursorLine: 0,
				cursorCol: 10,
			});
		} finally {
			rmSync(directory, { recursive: true, force: true });
		}
	});

	test("removes bundled metadata-only matches without changing unrelated commands", async () => {
		const directory = temporaryDirectory();
		try {
			const provider = createReviewAutocompleteProvider(createNativeProvider(directory), BASECAMP_DESCRIPTION);

			expect(await provider.getSuggestions(["/bundled"], 0, 8)).toBeNull();
			const green = await provider.getSuggestions(["/green"], 0, 6);
			expect(green?.items).toEqual([{ value: "green", label: "green", description: "Run green checks", icon: "G" }]);
			const similar = await provider.getSuggestions(["/review-"], 0, 8);
			expect(similar?.items.some((item) => item.value === "review-notes" && item.icon === "N")).toBe(true);
			const skill = await provider.getSuggestions(["/skill:rev"], 0, 10);
			expect(skill?.items.some((item) => item.value === "skill:review" && item.icon === "S")).toBe(true);
		} finally {
			rmSync(directory, { recursive: true, force: true });
		}
	});

	test("preserves forced file and command argument completions named review", async () => {
		const directory = temporaryDirectory();
		try {
			writeFileSync(join(directory, "review"), "file\n");
			const provider = createReviewAutocompleteProvider(createNativeProvider(directory), BASECAMP_DESCRIPTION);
			const files = await provider.getForceFileSuggestions?.(["rev"], 0, 3);
			const argument = await provider.getSuggestions(["/choose rev"], 0, 11);

			expect(files?.items.some((item) => item.value === "review")).toBe(true);
			expect(argument).toEqual({
				items: [{ value: "review", label: "review", description: "Argument named review", icon: "A" }],
				prefix: "rev",
			});
		} finally {
			rmSync(directory, { recursive: true, force: true });
		}
	});

	test("repeated wrapping keeps the same choices and native acceptance", async () => {
		const directory = temporaryDirectory();
		try {
			const once = createReviewAutocompleteProvider(createNativeProvider(directory), BASECAMP_DESCRIPTION);
			const twice = createReviewAutocompleteProvider(once, BASECAMP_DESCRIPTION);
			const result = await twice.getSuggestions(["/rev"], 0, 4);
			const review = reviewChoices(result)[0];

			expect(twice).toBe(once);
			expect(reviewChoices(result)).toHaveLength(1);
			if (!result || !review) throw new Error("Basecamp review completion missing");
			expect(twice.applyCompletion(["/rev"], 0, 4, review, result.prefix).lines).toEqual(["/review "]);
		} finally {
			rmSync(directory, { recursive: true, force: true });
		}
	});
});
