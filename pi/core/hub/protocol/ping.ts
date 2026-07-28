import type { ProtocolEnvelope } from "./version.ts";

/**
 * Application-level keepalive probe (either direction). The daemon also sends
 * it as the incumbent-liveness probe before accepting a duplicate registration;
 * the only correct answer is a pong with the same nonce.
 */
export interface PingFrame extends ProtocolEnvelope {
	type: "ping";
	nonce: string;
}

/** Answer to a ping keepalive probe; ignored when unsolicited. */
export interface PongFrame extends ProtocolEnvelope {
	type: "pong";
	nonce: string;
}
