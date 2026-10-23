"""
ConnectionManager tracks only the WebSocket connections held by THIS
process/replica in memory. Cross-replica fan-out is done via Redis
pub/sub (see core/redis_client.py) so a message sent on replica A
reaches a client connected to replica B. This is what makes the
"3 replicas behind Nginx" deployment actually work correctly instead
of silently dropping messages for users on other instances.
"""
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        # room_id -> {user_id: set(WebSocket)}  (a user can have multiple tabs/devices)
        self._rooms: dict[int, dict[int, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))

    def connect(self, room_id: int, user_id: int, ws: WebSocket) -> None:
        self._rooms[room_id][user_id].add(ws)

    def disconnect(self, room_id: int, user_id: int, ws: WebSocket) -> None:
        conns = self._rooms.get(room_id, {}).get(user_id)
        if conns and ws in conns:
            conns.remove(ws)
        if conns is not None and not conns:
            self._rooms[room_id].pop(user_id, None)
        if room_id in self._rooms and not self._rooms[room_id]:
            self._rooms.pop(room_id, None)

    def local_user_count(self, room_id: int) -> int:
        return len(self._rooms.get(room_id, {}))


                
    
    
    async def broadcast_local(
        self,
        room_id: int,
        payload: dict,
        exclude_ws: WebSocket | None = None,
    ) -> None:
        room = self._rooms.get(room_id, {})
        dead_connections = []

        for user_id, user_conns in list(room.items()):
            for ws in list(user_conns):
                if ws is exclude_ws:
                    continue

                try:
                    await ws.send_json(payload)
                except Exception:
                    # Record dead sockets and clean them up safely.
                    dead_connections.append((user_id, ws))

        for user_id, ws in dead_connections:
            self.disconnect(room_id, user_id, ws)
            


manager = ConnectionManager()
