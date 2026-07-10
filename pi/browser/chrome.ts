import { spawn } from "node:child_process";
import * as fsSync from "node:fs";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import puppeteer, { type Browser, type Page } from "puppeteer-core";
import { getBasecampEnv } from "#core/host/env.ts";
import { basecampRoot } from "#core/host/paths.ts";

const CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";
const REMOTE_DEBUGGING_PORT = 9222;
const BROWSER_URL = `http://localhost:${REMOTE_DEBUGGING_PORT}`;
const CONNECT_TIMEOUT_MS = 15_000;
const CONNECT_POLL_MS = 250;
const SINGLETON_FILES = ["SingletonLock", "SingletonSocket", "SingletonCookie"];

let browserSingleton: Browser | null = null;
let browserPromise: Promise<Browser> | null = null;

function profileDir(): string {
	return path.join(basecampRoot(), "browser", "profile");
}

function delay(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

function executableExists(executablePath: string): boolean {
	try {
		return fsSync.statSync(executablePath).isFile();
	} catch {
		return false;
	}
}

export function resolveExecutablePath(): string {
	const tried: string[] = [];
	const override = getBasecampEnv("BASECAMP_BROWSER_PATH");
	if (override) {
		tried.push(override);
		if (executableExists(override)) return override;
	}

	for (const candidate of [CHROME_PATH, BRAVE_PATH]) {
		tried.push(candidate);
		if (executableExists(candidate)) return candidate;
	}

	throw new Error(
		`Unable to find Chrome/Brave executable. Tried: ${tried.join(", ")}. Set BASECAMP_BROWSER_PATH to override.`,
	);
}

async function prepareProfileDir(): Promise<string> {
	const dir = profileDir();
	await fs.mkdir(dir, { recursive: true });
	await Promise.all(SINGLETON_FILES.map((name) => fs.rm(path.join(dir, name), { force: true }).catch(() => undefined)));
	return dir;
}

async function connectBrowser(): Promise<Browser> {
	const browser = await puppeteer.connect({ browserURL: BROWSER_URL, defaultViewport: null });
	browser.once("disconnected", () => {
		if (browserSingleton === browser) browserSingleton = null;
	});
	return browser;
}

async function pollConnect(): Promise<Browser> {
	const startedAt = Date.now();
	let lastError: unknown;
	while (Date.now() - startedAt < CONNECT_TIMEOUT_MS) {
		try {
			return await connectBrowser();
		} catch (error) {
			lastError = error;
			await delay(CONNECT_POLL_MS);
		}
	}
	const message = lastError instanceof Error ? lastError.message : String(lastError);
	throw new Error(`Timed out connecting to browser CDP at ${BROWSER_URL}: ${message}`);
}

async function launchAndConnect(): Promise<Browser> {
	try {
		return await connectBrowser();
	} catch {
		const executablePath = resolveExecutablePath();
		const dir = await prepareProfileDir();
		const child = spawn(
			executablePath,
			[
				`--remote-debugging-port=${REMOTE_DEBUGGING_PORT}`,
				`--user-data-dir=${dir}`,
				"--no-first-run",
				"--no-default-browser-check",
			],
			{ detached: true, stdio: "ignore" },
		);
		child.unref();
		return await pollConnect();
	}
}

export async function ensureBrowser(): Promise<Browser> {
	if (browserSingleton?.connected) return browserSingleton;
	browserSingleton = null;
	browserPromise ??= launchAndConnect().then(
		(browser) => {
			browserSingleton = browser;
			browserPromise = null;
			return browser;
		},
		(error: unknown) => {
			browserPromise = null;
			throw error;
		},
	);
	return await browserPromise;
}

export async function ensurePage(): Promise<Page> {
	const browser = await ensureBrowser();
	const pages = await browser.pages();
	return pages.at(-1) ?? (await browser.newPage());
}

export async function disconnectBrowser(): Promise<void> {
	const browser = browserSingleton;
	browserSingleton = null;
	browserPromise = null;
	if (browser) await browser.disconnect();
}
