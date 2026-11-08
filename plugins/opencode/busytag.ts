/**
 * busytag plugin for OpenCode 2: shows each OpenCode session on the Busy Tag display.
 *
 * Forwards session events to `busytag hook opencode` (JSON on stdin), which maps them to
 * working / done / attention / error, like the Claude Code hooks do. The agent ID is
 * `opencode:<sessionID>`, so its LEDs use the [agents.opencode] color from the busytag config.
 *
 * Install: `just install-opencode` (symlinks this file into ~/.config/opencode/plugins/).
 * OpenCode 1.x plugins have another shape; this one only runs on OpenCode 2.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

// The OpenCode service may not have ~/.local/bin (uv tool installs) on its PATH
const BUSYTAG =
	process.env.BUSYTAG_BIN ??
	[join(homedir(), ".local", "bin", "busytag")].find((path) => existsSync(path)) ??
	"busytag";

// Events that change what the display should show; everything else is ignored here
const FORWARDED = new Set([
	"session.execution.started",
	"session.execution.succeeded",
	"session.execution.failed",
	"session.execution.interrupted",
	"session.deleted",
	"permission.asked",
	"permission.replied",
	"form.created",
	"form.replied",
	"form.cancelled",
]);

// A subagent's prompts still need the user, so they are shown under the root session;
// its start and finish are not, or the parent would look done while still running
const PROMPTS = new Set([
	"permission.asked",
	"permission.replied",
	"form.created",
	"form.replied",
	"form.cancelled",
]);

interface Event {
	type: string;
	created?: number;
	location?: { directory?: string };
	data?: {
		sessionID?: string;
		parentID?: string;
		location?: { directory?: string };
		[key: string]: unknown;
	};
}

function report(payload: object): void {
	try {
		const child = spawn(BUSYTAG, ["hook", "opencode"], {
			stdio: ["pipe", "ignore", "ignore"],
			detached: true,
		});
		child.on("error", () => {});
		child.stdin?.on("error", () => {});
		child.stdin?.end(JSON.stringify(payload));
		child.unref();
	} catch {
		// The display is a nicety; never disturb OpenCode
	}
}

async function setup(ctx: any) {
	const parents = new Map<string, string>(); // subagent session -> its parent
	const directories = new Map<string, string>(); // root session -> project directory

	const root = (sessionID: string): string => {
		let current = sessionID;
		for (let depth = 0; parents.has(current) && depth < 10; depth++) {
			current = parents.get(current)!;
		}
		return current;
	};

	const handle = (event: Event): void => {
		const data = event.data ?? {};
		const sessionID = data.sessionID;
		if (!sessionID) return;

		if (event.type === "session.created" && data.parentID) {
			parents.set(sessionID, data.parentID);
			return;
		}
		if (!FORWARDED.has(event.type)) return;

		const isSubagent = parents.has(sessionID);
		if (isSubagent && !PROMPTS.has(event.type)) {
			if (event.type === "session.deleted") parents.delete(sessionID);
			return;
		}

		const rootID = root(sessionID);
		const directory =
			event.location?.directory ?? data.location?.directory ?? directories.get(rootID);
		if (directory) directories.set(rootID, directory);
		if (event.type === "session.deleted") directories.delete(rootID);

		report({
			type: event.type,
			created: event.created,
			sessionID: rootID,
			directory: directory ?? ctx.location?.directory,
			data,
		});
	};

	const controller = new AbortController();
	void (async () => {
		try {
			for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
				try {
					handle(event as Event);
				} catch {
					// Skip an event we could not read; keep listening
				}
			}
		} catch {
			// Subscription ended (unload or shutdown)
		}
	})();
	return () => controller.abort();
}

// OpenCode 2 loads a plugin's default export: its `id` and `setup`.
export default { id: "busytag", setup };
