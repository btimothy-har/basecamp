"""The agent-coordination feature hosted by the hub.

The runner and subprocess lifecycle (``runner``/``process``/``run_result``) plus
the transport-independent orchestration ``service`` layer (dispatch, wait, cancel,
peer messaging, workstreams) the hub exposes over its WS/HTTP surface.
"""
