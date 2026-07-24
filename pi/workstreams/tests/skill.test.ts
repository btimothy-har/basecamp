import assert from "node:assert/strict";
import * as fs from "node:fs";
import { describe, it } from "node:test";
import { workstreamsSkillPath } from "../index.ts";

describe("workstreams skill", () => {
	const skill = fs.readFileSync(workstreamsSkillPath, "utf8");

	it("owns the cross-tool sequencing that the copilot prompt no longer restates", () => {
		assert.match(skill, /^name: workstreams$/m);

		// record shaping
		assert.match(skill, /create_workstream/);
		assert.match(skill, /edit_workstream/);
		assert.match(skill, /keeps the old version/);
		assert.match(skill, /Before creating, call `list_workstreams`/);
		assert.match(skill, /set_workstream_status/);

		// execution staging, decoupled from the record
		assert.match(skill, /launch_workstream/);
		assert.match(skill, /\*\*It does not start an agent\.\*\*/);
		assert.match(skill, /infers the slug from the worktree label/);
		assert.match(skill, /`cd <worktree-path> && pi --workstream=<slug>`/);
		assert.match(skill, /launched into a different repo for cross-repo coordination/);

		// pull-based state, contact-address-only handles
		assert.match(skill, /ask_agent/);
		assert.match(skill, /contact address only/);
	});

	it("does not duplicate the copilot style's posture", () => {
		assert.doesNotMatch(skill, /do not supervise, drive, or manage it/);
		assert.doesNotMatch(skill, /Workstream agents never write Logseq/);
	});
});
