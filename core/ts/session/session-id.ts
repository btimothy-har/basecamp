/** Last 4 hex chars of UUIDv7 — random portion, safe for disambiguation. */
export function shortSessionId(sessionId: string): string {
	return sessionId.replace(/-/g, "").slice(-4);
}
