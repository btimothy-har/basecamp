/**
 * Shared skill invocation tracker.
 *
 * Records which skills the model has loaded via discover({ name }) during
 * the current session. Shared between footer.ts (display) and tool.ts
 * (dispatch guard).
 */

const invokedSkills = new Set<string>();

export function resetInvokedSkills(): void {
	invokedSkills.clear();
}

/**
 * Record a skill as invoked. Returns true if this is the first invocation
 * (caller may want to trigger a re-render or similar side-effect).
 */
export function trackSkillInvocation(name: string): boolean {
	const sizeBefore = invokedSkills.size;
	invokedSkills.add(name);
	return invokedSkills.size !== sizeBefore;
}

/** Returns true if the named skill has been invoked this session. */
export function hasInvokedSkill(name: string): boolean {
	return invokedSkills.has(name);
}

/** Returns invoked skills in invocation order for footer display. */
export function getInvokedSkills(): readonly string[] {
	return [...invokedSkills];
}
