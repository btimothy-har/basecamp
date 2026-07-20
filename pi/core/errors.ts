/** Error-formatting primitives shared across every domain. */

/** Extract a human-readable message from an unknown thrown value. */
export function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : String(error);
}
