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

export const Finding = Type.Object(
	{
		severity: Severity,
		file: NullableString,
		lineStart: NullableInteger,
		lineEnd: NullableInteger,
		title: Type.String(),
		detail: Type.String(),
		remediation: NullableString,
		dimension: Dimension,
		response: Type.Optional(Type.String()),
	},
	{ additionalProperties: false },
);
export type Finding = Static<typeof Finding>;

export const ReviewScope = Type.Object(
	{
		base: Type.String(),
		mergeBase: Type.String(),
		cwd: Type.String(),
		label: Type.String(),
	},
	{ additionalProperties: false },
);
export type ReviewScope = Static<typeof ReviewScope>;

export const ReportFindingsParams = Type.Object(
	{
		scope: ReviewScope,
		findings: Type.Array(Finding),
	},
	{ additionalProperties: false },
);
export type ReportFindingsParams = Static<typeof ReportFindingsParams>;

export const SEVERITY_RANK: Record<Severity, number> = {
	critical: 0,
	high: 1,
	medium: 2,
	low: 3,
};
