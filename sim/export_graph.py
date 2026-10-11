import json
import asyncio
import asyncpg
import os

async def export_graph():
    db_url = os.getenv("DATABASE_URL", "postgresql://geopulse:password@localhost:5432/geopulse_db")
    print(f"Connecting to {db_url}...")
    
    try:
        conn = await asyncpg.connect(db_url)
        
        nodes_query = "SELECT id, lon::float, lat::float FROM ways_vertices_pgr"
        edges_query = "SELECT gid as id, source, target, length_m as length FROM ways"
        
        nodes = await conn.fetch(nodes_query)
        edges = await conn.fetch(edges_query)
        
        graph_data = {
            "nodes": [dict(n) for n in nodes],
            "edges": [dict(e) for e in edges]
        }
        
        os.makedirs("sim", exist_ok=True)
        with open("sim/graph.json", "w") as f:
            json.dump(graph_data, f)
            
        print(f"Successfully exported {len(nodes)} nodes and {len(edges)} edges to sim/graph.json")
        await conn.close()
        
    except Exception as e:
        print(f"Error exporting graph: {e}")

if __name__ == "__main__":
    asyncio.run(export_graph())
