import type { Tool } from "@earendil-works/pi-ai";
import { type Static, Type } from "@sinclair/typebox";

export const Dimension = Type.Union([
	Type.Literal("security"),
	Type.Literal("testing"),
	Type.Literal("docs"),
	Type.Literal("clarity"),
	Type.Literal("conventions"),
	Type.Literal("general"),
]);
export type Dimension = Static<typeof Dimension>;

export const Severity = Type.Union([
	Type.Literal("critical"),
	Type.Literal("high"),
	Type.Literal("medium"),
	Type.Literal("low"),
]);
export type Severity = Static<typeof Severity>;

const NullableString = Type.Union([Type.String(), Type.Null()]);
const NullableInteger = Type.Union([Type.Integer(), Type.Null()]);

export const ExtractedFinding = Type.Object(
	{
		severity: Severity,
		file: NullableString,
		lineStart: NullableInteger,
		lineEnd: NullableInteger,
		title: Type.String(),
		detail: Type.String(),
		remediation: NullableString,
	},
	{ additionalProperties: false },
);
export type ExtractedFinding = Static<typeof ExtractedFinding>;

export const ReportFindingsArgs = Type.Object(
	{
		findings: Type.Array(ExtractedFinding),
	},
	{ additionalProperties: false },
);
export type ReportFindingsArgs = Static<typeof ReportFindingsArgs>;

export const Finding = Type.Composite([ExtractedFinding, Type.Object({ dimension: Dimension })], {
	additionalProperties: false,
});
export type Finding = Static<typeof Finding>;

export const report_findings: Tool<typeof ReportFindingsArgs> = {
	name: "report_findings",
	description: "Reports every distinct finding extracted from one prose code-review report.",
	parameters: ReportFindingsArgs,
};

export const SEVERITY_RANK: Record<Severity, number> = {
	critical: 0,
	high: 1,
	medium: 2,
	low: 3,
};
