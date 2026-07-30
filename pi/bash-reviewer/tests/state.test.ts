import assert from "node:assert/strict";
import { afterEach, beforeEach, describe, it } from "node:test";
import { isReviewerPaused, onReviewerPauseChange, setReviewerPaused } from "#bash-reviewer/state.ts";
import { getBasecampEnv, setBasecampEnv } from "#core/host/env.ts";

describe("reviewer pause state", () => {
	let prior: string | undefined;

	beforeEach(() => {
		prior = getBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED");
		setBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED", "");
	});

	afterEach(() => {
		if (prior === undefined) delete process.env.BASECAMP_BASH_REVIEWER_PAUSED;
		else setBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED", prior);
	});

	it("defaults to not paused", () => {
		assert.equal(isReviewerPaused(), false);
	});

	it("setReviewerPaused(true) sets the env var and reports paused", () => {
		setReviewerPaused(true);
		assert.equal(isReviewerPaused(), true);
		assert.equal(getBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED"), "1");
	});

	it("setReviewerPaused(false) clears the env var and reports not paused", () => {
		setReviewerPaused(true);
		setReviewerPaused(false);
		assert.equal(isReviewerPaused(), false);
		assert.equal(getBasecampEnv("BASECAMP_BASH_REVIEWER_PAUSED"), undefined);
	});

	it("fires listeners on change, not on no-op", () => {
		const events: boolean[] = [];
		const unsub = onReviewerPauseChange((paused) => events.push(paused));

		setReviewerPaused(true);
		setReviewerPaused(true); // no-op
		setReviewerPaused(false);

		assert.deepEqual(events, [true, false]);
		unsub();
	});

	it("unsubscribed listeners are not called", () => {
		const events: boolean[] = [];
		const unsub = onReviewerPauseChange((paused) => events.push(paused));
		unsub();

		setReviewerPaused(true);
		assert.deepEqual(events, []);
	});

	it("replaces the previous listener on re-register (reload safety)", () => {
		const first: boolean[] = [];
		const firstUnsub = onReviewerPauseChange((paused) => first.push(paused));

		// Simulate a /reload: a new module load registers a new listener without
		// an intervening session_shutdown for the old one. onReviewerPauseChange
		// must call the previous unsubscribe so the stale listener is removed.
		const second: boolean[] = [];
		const secondUnsub = onReviewerPauseChange((paused) => second.push(paused));

		setReviewerPaused(true);

		// Only the second listener should fire — the first was replaced.
		assert.deepEqual(first, []);
		assert.deepEqual(second, [true]);

		firstUnsub();
		secondUnsub();
	});
});
