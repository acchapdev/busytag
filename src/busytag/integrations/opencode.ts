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

interface SessionInfo {
	directory?: string;
	parentID?: string;
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
	// Session ID -> its folder and parent. Execution events carry neither, and through the
	// OpenCode service ctx.location is the service's folder, not the session's, so each
	// session is looked up once with ctx.session.get (seeded from session.created if seen).
	const sessions = new Map<string, Promise<SessionInfo>>();

	const lookup = (sessionID: string): Promise<SessionInfo> => {
		let info = sessions.get(sessionID);
		if (!info) {
			info = Promise.resolve()
				.then(() => ctx.session.get({ sessionID }))
				.then((session: any) => ({
					directory: session?.location?.directory,
					parentID: session?.parentID,
				}))
				.catch(() => ({}));
			sessions.set(sessionID, info);
		}
		return info;
	};

	const root = async (sessionID: string): Promise<[string, SessionInfo]> => {
		let current = sessionID;
		let info = await lookup(current);
		for (let depth = 0; info.parentID && depth < 10; depth++) {
			current = info.parentID;
			info = await lookup(current);
		}
		return [current, info];
	};

	const handle = async (event: Event): Promise<void> => {
		const data = event.data ?? {};
		const sessionID = data.sessionID;
		if (!sessionID) return;

		if (event.type === "session.created") {
			sessions.set(
				sessionID,
				Promise.resolve({ directory: data.location?.directory, parentID: data.parentID }),
			);
			return;
		}
		if (!FORWARDED.has(event.type)) return;

		const [rootID, rootInfo] = await root(sessionID);
		const isSubagent = rootID !== sessionID;
		if (event.type === "session.deleted") sessions.delete(sessionID);
		if (isSubagent && !PROMPTS.has(event.type)) return;

		report({
			type: event.type,
			created: event.created,
			sessionID: rootID,
			directory: rootInfo.directory ?? event.location?.directory ?? ctx.location?.directory,
			data,
		});
	};

	const controller = new AbortController();
	void (async () => {
		try {
			for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
				// Not awaited: a lookup must not hold up later events. Reports carry the
				// event's own time, so busytag still applies them in order.
				handle(event as Event).catch(() => {
					// Skip an event we could not read; keep listening
				});
			}
		} catch {
			// Subscription ended (unload or shutdown)
		}
	})();
	return () => controller.abort();
}

// OpenCode 2 loads a plugin's default export: its `id` and `setup`.
export default { id: "busytag", setup };
