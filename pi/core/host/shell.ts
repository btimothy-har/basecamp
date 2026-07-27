/**
 * POSIX single-quote escaping: wrap `arg` in single quotes, replacing every
 * embedded `'` with `'\''`. The result is safe to paste into a shell command
 * verbatim — the string is interpreted literally with no metacharacter
 * expansion.
 */
export function shellQuote(arg: string): string {
	return `'${arg.replaceAll("'", "'\\''")}'`;
}
