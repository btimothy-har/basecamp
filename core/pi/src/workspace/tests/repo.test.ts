import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { deriveRepoIdentity } from "../repo.ts";

describe("deriveRepoIdentity", () => {
	it("derives identities from scp-like remotes", () => {
		assert.equal(deriveRepoIdentity("git@github.com:org/name.git", "fallback"), "org/name");
	});

	it("derives identities from ssh URL remotes", () => {
		assert.equal(deriveRepoIdentity("ssh://git@github.com/org/name.git", "fallback"), "org/name");
	});

	it("derives identities from https URL remotes without .git", () => {
		assert.equal(deriveRepoIdentity("https://github.com/org/name", "fallback"), "org/name");
	});

	it("derives identities from https URL remotes with .git", () => {
		assert.equal(deriveRepoIdentity("https://github.com/org/name.git", "fallback"), "org/name");
	});

	it("derives identities from remotes ending in .git with a trailing slash", () => {
		assert.equal(deriveRepoIdentity("https://github.com/org/name.git/", "fallback"), "org/name");
	});

	it("falls back for hostless/raw paths and dot segments", () => {
		assert.equal(deriveRepoIdentity("../repo.git", "fallback"), "fallback");
		assert.equal(deriveRepoIdentity("/local/path/repo.git", "fallback"), "fallback");
	});

	it("derives identities from non-GitHub hosts", () => {
		assert.equal(deriveRepoIdentity("git@gitlab.com:group/sub.git", "fallback"), "group/sub");
	});

	it("falls back without a remote", () => {
		assert.equal(deriveRepoIdentity(null, "fallback"), "fallback");
	});

	it("falls back with an empty remote", () => {
		assert.equal(deriveRepoIdentity("", "fallback"), "fallback");
		assert.equal(deriveRepoIdentity("  ", "fallback"), "fallback");
	});

	it("falls back for a single-segment unparseable path", () => {
		assert.equal(deriveRepoIdentity("not-a-url", "fallback"), "fallback");
	});
});
