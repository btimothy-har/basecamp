import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { type Triage, triageCommand } from "#bash-reviewer/triage/index.ts";

const allow: Triage = { kind: "allow" };
const dangerousShell: Triage = { kind: "gate", failClosed: false, category: "dangerous-shell" };
const irreversibleRemote: Triage = { kind: "gate", failClosed: true, category: "irreversible-remote" };

function assertTriage(command: string, expected: Triage): void {
	assert.deepEqual(triageCommand(command), expected, command);
}

describe("bash triage segment splitting", () => {
	it("gates dangerous commands on any line of a multi-line command", () => {
		for (const command of [
			"git status\nrm -rf build",
			"set -euo pipefail\nchmod -R a+rX /app/model_cache",
			"set -euo pipefail\nrm -rf /tmp/build",
			"set -euo pipefail\ncd /tmp/work\nrm -rf artifacts",
			"echo start\nls -la\nshred secret",
			"echo $((x << n))\nrm -rf build",
			"rm \\\n-rf /x",
		]) {
			assertTriage(command, dangerousShell);
		}

		assertTriage("git status\ngit push --force origin main", irreversibleRemote);
		assertTriage("cat <<EOF > notes.txt\nsome text\nEOF\ngit push --force origin main", irreversibleRemote);
	});

	it("treats newlines inside quotes, heredoc bodies, and continuations as data", () => {
		for (const command of [
			"git status\nls -la",
			"printf 'a\nb'",
			'echo "one\ntwo"',
			"echo $'one\ntwo'",
			"cat <<EOF > notes.txt\nrm -rf /\nEOF",
			"cat <<-'EOF' > notes.txt\n\trm -rf /\n\tEOF",
			"git \\\n  status",
			"echo $((1 << 2))\nls",
		]) {
			assertTriage(command, allow);
		}
	});

	it("never mistakes an arithmetic shift for a heredoc opener", () => {
		assertTriage("echo $((1 << n ))\nrm -rf /x", dangerousShell);
		assertTriage("a=$(( 1 << n ))\nrm -rf /x", dangerousShell);
		assertTriage(": $(( 1 << bits ))\ngit push --force origin main", irreversibleRemote);
	});

	it("rescans unterminated heredoc bodies as code instead of dropping them", () => {
		assertTriage("cat <<E-F\necho <<EOF\nE-F\nrm -rf /x", dangerousShell);
		assertTriage("cat <<EOF > notes.txt\nrm -rf /", dangerousShell);
	});

	it("splits on a lone & but not on redirection ampersands", () => {
		assertTriage("ls & rm -rf /x", dangerousShell);
		assertTriage("true & git push --force origin main", irreversibleRemote);
		assertTriage("sleep 5 & echo hi", allow);
		assertTriage("cmd > log 2>&1\nls", allow);
	});

	it("keeps quoted separators inside one segment so assignment prefixes are skipped", () => {
		assertTriage("X='a;b' rm -rf /z", dangerousShell);
		assertTriage('env FOO="a|b" rm -rf /z', dangerousShell);

		const wideSearch = triageCommand("X='a;b' grep -r foo /");
		assert.equal(wideSearch.kind, "block");
		if (wideSearch.kind === "block") assert.match(wideSearch.reason, /Wide-ranging filesystem search blocked/);
	});

	it("triages heredoc bodies fed to a shell interpreter", () => {
		assertTriage("bash <<EOF\ncd /x; rm -rf .\nEOF", dangerousShell);
		assertTriage("sh <<'EOF'\ngit push --force origin main\nEOF", irreversibleRemote);
	});

	it("skips leading redirections when locating the executable", () => {
		// Redirections may legally precede the command word; the operator token
		// must not occupy the executable position and hide the command.
		assertTriage("<<EOF bash\nrm -rf /x\nEOF", dangerousShell);
		assertTriage("<< EOF bash\nrm -rf /x\nEOF", dangerousShell);
		assertTriage("<<'EOF' sh\ngit push --force origin main\nEOF", irreversibleRemote);
		assertTriage("< /dev/null rm -rf /x", dangerousShell);
		assertTriage("2>/dev/null git push --force origin main", irreversibleRemote);
		assertTriage("> /tmp/out rm -rf /x", dangerousShell);

		// `bash` here is cat's argument, not the interpreter: the body stays data.
		assertTriage("cat <<EOF bash\nrm -rf /\nEOF", allow);
		// A digit-leading executable is not an fd-prefixed redirection.
		assertTriage("7z x archive.7z", allow);
		assertTriage("git status 2>/dev/null", allow);
	});

	it("ends a word at a glued redirection so the executable stays visible", () => {
		// A shell ends a word at a redirection without needing whitespace, so
		// `rm>file` is `rm` redirected. Fusing it into one token left the
		// executable matching no known command name and allowed the segment.
		assertTriage("rm>file -rf /x", dangerousShell);
		assertTriage("bash<<EOF\nrm -rf /tmp/x\nEOF", dangerousShell);
		assertTriage("sudo>out rm -rf /x", dangerousShell);
		assertTriage("env>x FOO=bar rm -rf /x", dangerousShell);
		// A glued redirection on a flag must not downgrade the verdict either.
		assertTriage("git push --force>x origin main", irreversibleRemote);

		// Quoted metacharacters remain data, and an fd prefix stays with its operator.
		assertTriage('echo "a>b"', allow);
		assertTriage("grep 'a > b' file.txt", allow);
		assertTriage("ls 2>&1", allow);
	});
});
