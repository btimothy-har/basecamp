/**
 * Display sanitization, truncation, and byte-formatting helpers for the bq_query tool.
 */

import { ANSI_ESCAPE_PATTERN, CONTROL_CHARS_PATTERN, DISPLAY_ELLIPSIS, MAX_DESCRIPTION_CHARS } from "./params.ts";

export function trimOrNull(value: string | undefined): string | null {
	const trimmed = value?.trim();
	return trimmed ? trimmed : null;
}

export function sanitizeQueryDescription(value: unknown): string {
	if (typeof value !== "string") {
		throw new Error("description is required and must be a non-empty TLDR of the query.");
	}

	const sanitized = value
		.replace(ANSI_ESCAPE_PATTERN, " ")
		.replace(CONTROL_CHARS_PATTERN, " ")
		.replace(/\s+/g, " ")
		.trim();

	if (!sanitized) {
		throw new Error("description is required and must be a non-empty TLDR of the query.");
	}

	return truncateForDisplay(sanitized, MAX_DESCRIPTION_CHARS);
}

export function displayLength(value: string): number {
	return Array.from(value).length;
}

function truncateForDisplay(value: string, maxChars: number): string {
	const chars = Array.from(value);
	if (chars.length <= maxChars) return value;
	if (maxChars <= 0) return "";
	if (maxChars === 1) return DISPLAY_ELLIPSIS;
	return `${chars
		.slice(0, maxChars - 1)
		.join("")
		.trimEnd()}${DISPLAY_ELLIPSIS}`;
}

function truncatePathTail(value: string, maxChars: number): string {
	const chars = Array.from(value);
	if (chars.length <= maxChars) return value;
	if (maxChars <= 0) return "";
	if (maxChars === 1) return DISPLAY_ELLIPSIS;
	return `${DISPLAY_ELLIPSIS}${chars.slice(-(maxChars - 1)).join("")}`;
}

export function descriptionPreview(value: unknown, maxChars: number): string | null {
	try {
		return truncateForDisplay(sanitizeQueryDescription(value), maxChars);
	} catch {
		return null;
	}
}

export function sqlPathPreview(value: unknown, maxChars: number): string {
	if (typeof value !== "string") return "...";
	const sanitized = value
		.replace(ANSI_ESCAPE_PATTERN, " ")
		.replace(CONTROL_CHARS_PATTERN, " ")
		.replace(/\s+/g, " ")
		.trim();
	return sanitized ? truncatePathTail(sanitized, maxChars) : "...";
}

export function safeApprovalPromptValue(value: string | null, fallback: string): string {
	if (!value) return fallback;
	const sanitized = value
		.replace(ANSI_ESCAPE_PATTERN, " ")
		.replace(CONTROL_CHARS_PATTERN, " ")
		.replace(/\s+/g, " ")
		.trim();
	return sanitized || fallback;
}

export function formatBytes(bytes: string | null): string {
	if (!bytes) return "unknown";
	const value = Number(bytes);
	if (!Number.isFinite(value)) return `${bytes} bytes`;
	const units = ["bytes", "KiB", "MiB", "GiB", "TiB", "PiB"];
	let scaled = value;
	let unit = units[0] ?? "bytes";
	for (const candidate of units) {
		unit = candidate;
		if (Math.abs(scaled) < 1024 || candidate === units[units.length - 1]) break;
		scaled /= 1024;
	}
	return unit === "bytes" ? `${value} bytes` : `${scaled.toFixed(2)} ${unit}`;
}

function formatDecimalBytes(bytes: string | null): string {
	if (!bytes) return "unknown";
	const value = Number(bytes);
	if (!Number.isFinite(value)) return `${bytes} bytes`;
	const units = ["bytes", "KB", "MB", "GB", "TB", "PB"];
	let scaled = value;
	let unit = units[0] ?? "bytes";
	for (const candidate of units) {
		unit = candidate;
		if (Math.abs(scaled) < 1000 || candidate === units[units.length - 1]) break;
		scaled /= 1000;
	}
	return unit === "bytes" ? `${value} bytes` : `${scaled.toFixed(2)} ${unit}`;
}

export function formatScanBytes(bytes: string | null): string {
	return formatDecimalBytes(bytes);
}
