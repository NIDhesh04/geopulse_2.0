class FakeRouting:
    def __init__(self):
        self.multipliers = {}
        self.connected = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def route(self, start_lat, start_lon, end_lat, end_lon):
        return [{"node": 1, "edge": 100, "cost": 1.0}]

    async def snap_to_edge(self, lat, lon):
        return {"id": 100, "source_node_id": 1, "target_node_id": 2}

    async def apply_multipliers(self, multipliers_dict):
        for k, v in multipliers_dict.items():
            self.multipliers[k] = v

    async def get_multipliers(self):
        return self.multipliers

    async def reset_multipliers(self):
        self.multipliers.clear()
