function quotePatchPath(prefix: "a" | "b", path: string): string {
	const bytes = Buffer.from(`${prefix}/${path}`, "utf8");
	const plain = bytes.every((byte) => byte > 32 && byte < 127 && byte !== 34 && byte !== 92);
	if (plain) return bytes.toString("utf8");
	let quoted = '"';
	for (const byte of bytes) {
		quoted +=
			byte > 32 && byte < 127 && byte !== 34 && byte !== 92
				? String.fromCharCode(byte)
				: `\\${byte.toString(8).padStart(3, "0")}`;
	}
	return `${quoted}"`;
}

/** Relabel an absolute no-index patch as one repository-relative file. */
export function relabelNoIndexPatch(patch: string, path: string): string {
	if (patch.length === 0) return patch;
	const oldPath = quotePatchPath("a", path);
	const newPath = quotePatchPath("b", path);
	let inHunk = false;
	return patch
		.split("\n")
		.map((line) => {
			if (line.startsWith("@@ ")) inHunk = true;
			if (inHunk) return line;
			if (line.startsWith("diff --git ")) return `diff --git ${oldPath} ${newPath}`;
			if (line.startsWith("--- ")) return `--- ${oldPath}`;
			if (line.startsWith("+++ ")) return `+++ ${newPath}`;
			return line;
		})
		.join("\n");
}

/** Parse untracked paths without mistaking rename/copy source fields for records. */
export function parseUntrackedPorcelain(status: string): string[] {
	const fields = status.split("\0");
	const paths: string[] = [];
	for (let index = 0; index < fields.length; index++) {
		const record = fields[index];
		if (!record || record.length < 3 || record.charAt(2) !== " ") continue;
		const code = record.slice(0, 2);
		if (code === "??") paths.push(record.slice(3));
		if (code.includes("R") || code.includes("C")) index += 1;
	}
	return paths;
}
