#!/usr/bin/env python3
"""Calcula el camino mas corto entre el vehiculo y el destino sobre el grafo
de waypoints armado en map_editor.html (nodos + conexiones dibujadas a mano
+ destino marcado), usando Dijkstra bidireccional: busca simultaneamente
desde el origen y desde el destino, y se detiene cuando las dos busquedas se
cruzan. El orden en que se cargaron los waypoints en el mapa NO importa -
justamente ese es el problema que resuelve este algoritmo.

Uso standalone (sin ROS, ya utilizable hoy sin esperar al GPS):
    python3 waypoint_router.py grafo.json <origen_id> [destino_id]

Fase 1.6+ (cuando el origen real venga del GPS via navsat_transform_node):
compute_route() esta pensado para llamarse desde un nodo que sepa la
posicion real del vehiculo (buscando el nodo del grafo mas cercano a esa
posicion como origen).
"""
import heapq
import json
import math
import sys


def haversine_m(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos lat/lon (formula de haversine)."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_adjacency(graph):
    """graph = {'nodes': [{'id','lat','lon'}, ...], 'edges': [[a,b], ...]}"""
    coords = {n['id']: (n['lat'], n['lon']) for n in graph['nodes']}
    adj = {nid: [] for nid in coords}
    for a, b in graph['edges']:
        w = haversine_m(coords[a][0], coords[a][1], coords[b][0], coords[b][1])
        adj[a].append((b, w))
        adj[b].append((a, w))
    return adj, coords


def bidirectional_dijkstra(adj, start, goal):
    """adj: {id: [(vecino, peso), ...]}. Devuelve (distancia_total, [ids del
    camino start->goal]) o (None, None) si no hay camino."""
    if start == goal:
        return 0.0, [start]
    if start not in adj or goal not in adj:
        return None, None

    INF = float('inf')
    dist_f, dist_b = {start: 0.0}, {goal: 0.0}
    parent_f, parent_b = {start: None}, {goal: None}
    visited_f, visited_b = set(), set()
    pq_f, pq_b = [(0.0, start)], [(0.0, goal)]

    best_dist = INF
    meeting_node = None

    def settle(pq, dist, parent, visited, dist_other):
        nonlocal best_dist, meeting_node
        d, u = heapq.heappop(pq)
        if u in visited:
            return
        visited.add(u)
        if u in dist_other:
            total = dist[u] + dist_other[u]
            if total < best_dist:
                best_dist = total
                meeting_node = u
        for v, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, INF):
                dist[v] = nd
                parent[v] = u
                heapq.heappush(pq, (nd, v))

    while pq_f and pq_b:
        # Criterio de corte estandar: si la suma de las dos mejores
        # prioridades pendientes ya supera la mejor union encontrada, ningun
        # camino futuro puede mejorarla.
        if pq_f[0][0] + pq_b[0][0] >= best_dist:
            break
        if pq_f[0][0] <= pq_b[0][0]:
            settle(pq_f, dist_f, parent_f, visited_f, dist_b)
        else:
            settle(pq_b, dist_b, parent_b, visited_b, dist_f)

    if meeting_node is None:
        return None, None

    path_f = []
    node = meeting_node
    while node is not None:
        path_f.append(node)
        node = parent_f[node]
    path_f.reverse()

    path_b = []
    node = parent_b[meeting_node]
    while node is not None:
        path_b.append(node)
        node = parent_b[node]

    return best_dist, path_f + path_b


def compute_route(graph, origin_id, destino_id=None):
    destino_id = destino_id if destino_id is not None else graph.get('destino')
    if destino_id is None:
        raise ValueError("no hay destino marcado en el grafo")
    adj, coords = build_adjacency(graph)
    dist, path = bidirectional_dijkstra(adj, origin_id, destino_id)
    if path is None:
        return None
    return {
        'distance_m': dist,
        'path_ids': path,
        'path_latlon': [coords[n] for n in path],
    }


def nearest_node(graph, lat, lon):
    """Util para cuando el origen es una posicion real (GPS), no un id de
    nodo del grafo: busca el waypoint mas cercano para usar como origen."""
    best_id, best_d = None, float('inf')
    for n in graph['nodes']:
        d = haversine_m(lat, lon, n['lat'], n['lon'])
        if d < best_d:
            best_id, best_d = n['id'], d
    return best_id


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Uso: python3 waypoint_router.py <grafo.json> <origen_id> [destino_id]")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        graph = json.load(f)
    origin = int(sys.argv[2])
    destino = int(sys.argv[3]) if len(sys.argv) > 3 else None
    result = compute_route(graph, origin, destino)
    if result is None:
        print("Sin camino posible entre esos dos puntos.")
        sys.exit(2)
    print(json.dumps(result, indent=2))
