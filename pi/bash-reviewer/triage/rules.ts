/** Triage verdicts and the static rule tables the classifiers consult. */

export type Triage =
	| { kind: "allow" }
	| { kind: "block"; reason: string }
	| { kind: "gate"; failClosed: boolean; category: string };

export const ALLOW: Triage = { kind: "allow" };
export const GIT_MUTATION: Triage = { kind: "gate", failClosed: false, category: "git-mutation" };
export const GH_MUTATION: Triage = { kind: "gate", failClosed: false, category: "gh-mutation" };
export const DANGEROUS_SHELL: Triage = { kind: "gate", failClosed: false, category: "dangerous-shell" };
export const IRREVERSIBLE_REMOTE: Triage = { kind: "gate", failClosed: true, category: "irreversible-remote" };
export const BQ_QUERY_BLOCK: Triage = {
	kind: "block",
	reason:
		'Raw `bq query` execution through bash is blocked. Write the SQL to a .sql file and use bq_query({ path: "..." }) instead.',
};
export const WORKTREE_BLOCK: Triage = {
	kind: "block",
	reason:
		"Direct `git worktree` subcommands are blocked. Worktree management is automated through the `plan()` tool's approval flow — submit an implementation plan to activate an execution worktree, or use `/worktree` to switch.",
};

export const READ_ONLY_COMMANDS = new Set([
	"annotate",
	"blame",
	"bugreport",
	"cat-file",
	"check-attr",
	"check-ignore",
	"check-mailmap",
	"check-ref-format",
	"cherry",
	"column",
	"count-objects",
	"describe",
	"diagnose",
	"diff",
	"diff-files",
	"diff-index",
	"diff-pairs",
	"diff-tree",
	"for-each-ref",
	"fsck",
	"fsck-objects",
	"get-tar-commit-id",
	"grep",
	"help",
	"last-modified",
	"log",
	"ls-files",
	"ls-remote",
	"ls-tree",
	"merge-base",
	"merge-tree",
	"name-rev",
	"patch-id",
	"range-diff",
	"rev-list",
	"rev-parse",
	"shortlog",
	"show",
	"show-branch",
	"show-index",
	"show-ref",
	"status",
	"var",
	"verify-commit",
	"verify-pack",
	"verify-tag",
	"version",
	"whatchanged",
]);

export const GH_ALLOW: RegExp[] = [
	/^gh\s+issue\s+(view|list|ls|status)(\s|$)/,
	/^gh\s+(pr|run)\s+(view|list|diff|checks|status)(\s|$)/,
	/^gh\s+pr\s+checkout(\s|$)/,
	/^gh\s+repo\s+(view|list|clone)(\s|$)/,
	/^gh\s+run\s+watch(\s|$)/,
	/^gh\s+search\s/,
	/^gh\s+browse(\s|$)/,
];

export const BQ_GLOBAL_FLAGS_WITH_VALUE = new Set([
	"api",
	"api_version",
	"apilog",
	"application_default_credential_file",
	"bigqueryrc",
	"billing_project",
	"ca_certificates_file",
	"client_id",
	"client_secret",
	"credential_file",
	"dataset_id",
	"discovery_file",
	"flagfile",
	"format",
	"httplib2_debuglevel",
	"job_id_prefix",
	"location",
	"max_rows_per_request",
	"oauth2_credential_file",
	"project_id",
	"proxy_address",
	"proxy_password",
	"proxy_port",
	"proxy_username",
	"service_account",
	"service_account_credential_file",
	"trace",
]);

export const GIT_GLOBAL_FLAGS_WITH_VALUE = new Set([
	"-C",
	"-c",
	"--git-dir",
	"--work-tree",
	"--namespace",
	"--exec-path",
	"--config-env",
]);

export const WRAPPER_SKIP_ONE = new Set(["command", "nohup"]);
export const SUDO_FLAGS_WITH_VALUE = new Set([
	"-A",
	"-a",
	"-b",
	"-C",
	"-c",
	"-D",
	"-e",
	"-g",
	"-h",
	"-p",
	"-R",
	"-r",
	"-T",
	"-t",
	"-U",
	"-u",
	"--askpass",
	"--background",
	"--chdir",
	"--close-from",
	"--group",
	"--host",
	"--login-class",
	"--prompt",
	"--role",
	"--type",
	"--user",
	"--other-user",
]);
export const NICE_FLAGS_WITH_VALUE = new Set(["-n", "--adjustment"]);
export const IONICE_FLAGS_WITH_VALUE = new Set(["-c", "--class", "-n", "--classdata"]);
export const TIME_FLAGS_WITH_VALUE = new Set(["-f", "--format", "-o", "--output"]);
export const SHELLS = new Set(["bash", "dash", "fish", "ksh", "sh", "zsh"]);
export const NETWORK_PIPE_SHELLS = new Set(["bash", "sh", "zsh"]);
export const NETWORK_FETCHERS = new Set(["curl", "wget"]);

export const GREP_SEARCH_TOOLS = new Set(["grep", "egrep", "fgrep"]);
export const RECURSIVE_SEARCH_TOOLS = new Set(["rg", "ag", "ack", "fd", "fdfind"]);
export const WIDE_ROOTS = new Set([
	"/",
	"~",
	"$HOME",
	// biome-ignore lint/suspicious/noTemplateCurlyInString: literal shell token, not a JS template placeholder
	"${HOME}",
	"/etc",
	"/usr",
	"/var",
	"/opt",
	"/bin",
	"/sbin",
	"/dev",
	"/proc",
	"/sys",
	"/System",
	"/Library",
	"/Applications",
	"/private",
	"/Volumes",
	"/Users",
	"/home",
	"/root",
]);

function triageSeverity(triage: Triage): number {
	if (triage.kind === "block") return 3;
	if (triage.kind === "gate" && triage.failClosed) return 2;
	if (triage.kind === "gate") return 1;
	return 0;
}

export function mergeTriage(left: Triage, right: Triage): Triage {
	return triageSeverity(right) > triageSeverity(left) ? right : left;
}
